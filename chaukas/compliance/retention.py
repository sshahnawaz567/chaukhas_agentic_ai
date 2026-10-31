"""Retention + erasure (P2): purge/anonymise `turns` after the retention window;
on an erasure request anonymise the merchant's PII everywhere EXCEPT records the
law requires us to keep (audit_log stays — it never holds raw PII anyway).

Owner: Member 2 · COMPLIANCE.md D6, D7

What is erased and what is kept (DPDP s.8, s.11-12):
  erased / anonymised  merchants (name + the five PII columns), turns.text_masked, handoffs.brief_json 'asked',
                       the merchant's trace files
  kept (record keeping) audit_log, executions, offers, consents, tickets, ticket_events, settlements,
                       cashflow_features: they hold ids, amounts and already-masked text, never raw PII.
                       audit_log, executions and consents are also append-only by DB triggers.
The merchants row itself stays (other tables point at it); only its personal fields are blanked.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chaukas.compliance import consent
from chaukas.db import query_one
from chaukas.observability import trace
from chaukas.policy import engine
from chaukas.privacy.pii import mask

_ISO = "%Y-%m-%dT%H:%M:%SZ"
RETENTION_MARK = "[erased: retention window]"
ERASED_MARK = "[erased at the merchant's request]"
ERASED_NAME = "Erased merchant"

PII_COLUMNS = ("phone", "vpa", "pan", "account_no", "ifsc")

# why each table is kept after an erasure request (returned in the receipt, shown to the merchant)
RETAINED = {
    "audit_log": "append-only decision record; holds masked values only",
    "executions": "append-only record of what ran; ids and amounts only",
    "offers": "loan offer records (RBI Digital Lending record keeping)",
    "insurance_leads": "insurance interest records: ids, product and illustrative amounts only",
    "consents": "append-only proof of consent given and withdrawn (DPDP s.6)",
    "tickets": "support tickets: needed to complete the service; masked text only",
    "ticket_events": "ticket timeline; masked text only",
    "settlements": "financial ledger records",
    "cashflow_features": "aggregated features, no identity",
}


class MerchantNotFound(LookupError):
    """No such merchant."""


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def retention_days(policy: dict | None = None) -> int:
    """The window in days, from config/policy.yaml (never hard-coded)."""
    days = (policy or engine.load_policy()).get("retention_days")
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        raise ValueError("config/policy.yaml retention_days must be a positive integer")
    return days


# ------------------------------------------------------------------ D6: retention window

def purge_turns(conn: sqlite3.Connection, *, now: datetime | None = None, days: int | None = None) -> int:
    """Replace the text of every turn older than the window. The row stays (turn_no, lang, intent are
    analytics, not personal data). Returns how many turns were changed; running it again changes nothing."""
    cutoff = (_now(now) - timedelta(days=days or retention_days())).strftime(_ISO)
    cur = conn.execute(
        "UPDATE turns SET text_masked = ? WHERE created_at < ? AND text_masked NOT IN (?, ?)",
        (RETENTION_MARK, cutoff, RETENTION_MARK, ERASED_MARK))
    conn.commit()
    return cur.rowcount


def purge_traces(*, trace_dir: Path | None = None, now: datetime | None = None, days: int | None = None) -> int:
    """Delete trace files not written to for longer than the window. Returns how many were deleted."""
    folder = Path(trace_dir) if trace_dir else trace.trace_dir()
    if not folder.exists():
        return 0
    cutoff = (_now(now) - timedelta(days=days or retention_days())).timestamp()
    deleted = 0
    for f in folder.glob("*.jsonl"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    return deleted


def purge(conn: sqlite3.Connection, *, now: datetime | None = None, days: int | None = None,
          trace_dir: Path | None = None) -> dict:
    """Run the whole retention sweep (turns + traces)."""
    window = days or retention_days()
    return {"retention_days": window,
            "turns_anonymised": purge_turns(conn, now=now, days=window),
            "trace_files_deleted": purge_traces(trace_dir=trace_dir, now=now, days=window)}


# ------------------------------------------------------------------ D7: access summary + erasure

def _require(conn: sqlite3.Connection, merchant_id: str) -> sqlite3.Row:
    row = query_one(conn, "SELECT * FROM merchants WHERE merchant_id = ?", (merchant_id,))
    if row is None:
        raise MerchantNotFound(merchant_id)
    return row


def _count(conn: sqlite3.Connection, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def data_summary(conn: sqlite3.Connection, merchant_id: str) -> dict:
    """What we hold about this merchant (the right to access). Personal fields come back MASKED."""
    m = _require(conn, merchant_id)
    profile = {"name": mask(m["name"], "name")}
    for col in PII_COLUMNS:
        profile[col] = mask(m[col], col) if m[col] else None
    profile.update({"preferred_lang": m["preferred_lang"], "device": m["device"], "kyc_status": m["kyc_status"]})
    sessions = "(SELECT session_id FROM sessions WHERE merchant_id = ?)"
    return {
        "merchant_id": merchant_id,
        "profile": profile,
        "counts": {
            "sessions": _count(conn, "SELECT COUNT(*) FROM sessions WHERE merchant_id = ?", merchant_id),
            "turns": _count(conn, f"SELECT COUNT(*) FROM turns WHERE session_id IN {sessions}", merchant_id),
            "tickets": _count(conn, "SELECT COUNT(*) FROM tickets WHERE merchant_id = ?", merchant_id),
            "offers": _count(conn, "SELECT COUNT(*) FROM offers WHERE merchant_id = ?", merchant_id),
            "insurance_leads": _count(conn, "SELECT COUNT(*) FROM insurance_leads WHERE merchant_id = ?", merchant_id),
            "handoffs": _count(conn, "SELECT COUNT(*) FROM handoffs WHERE merchant_id = ?", merchant_id),
            "audit_log": _count(conn, "SELECT COUNT(*) FROM audit_log WHERE merchant_id = ?", merchant_id),
        },
        "consents": consent.current_state(conn, merchant_id),
        "retention_days": retention_days(),
        "kept_after_erasure": RETAINED,
    }


def erase_merchant(conn: sqlite3.Connection, merchant_id: str, *, now: datetime | None = None,
                   trace_dir: Path | None = None) -> dict:
    """Erasure request: blank the merchant's personal data, withdraw both consents (so no offer is made
    again), and keep only the records the law requires. Safe to run twice. Returns a receipt."""
    _require(conn, merchant_id)

    withdrawn = [p for p in consent.PURPOSES if not consent.is_withdrawn(conn, merchant_id, p)]
    for purpose in consent.PURPOSES:
        consent.withdraw(conn, merchant_id, purpose, channel="chat")

    cur = conn.execute(
        f"UPDATE merchants SET name = ?, {', '.join(c + ' = NULL' for c in PII_COLUMNS)} WHERE merchant_id = ?",
        (ERASED_NAME, merchant_id))
    merchants_changed = cur.rowcount

    session_ids = "(SELECT session_id FROM sessions WHERE merchant_id = ?)"
    trace_ids = [r[0] for r in conn.execute(
        f"SELECT DISTINCT trace_id FROM turns WHERE session_id IN {session_ids}", (merchant_id,))]
    trace_ids += [r[0] for r in conn.execute(
        "SELECT DISTINCT trace_id FROM audit_log WHERE merchant_id = ? AND trace_id IS NOT NULL", (merchant_id,))]

    turns_changed = conn.execute(
        f"UPDATE turns SET text_masked = ? WHERE session_id IN {session_ids} AND text_masked != ?",
        (ERASED_MARK, merchant_id, ERASED_MARK)).rowcount

    handoffs_changed = 0
    for row in conn.execute("SELECT id, brief_json FROM handoffs WHERE merchant_id = ?", (merchant_id,)).fetchall():
        brief = json.loads(row["brief_json"])
        if brief.get("asked") != ERASED_MARK:
            brief["asked"] = ERASED_MARK
            conn.execute("UPDATE handoffs SET brief_json = ? WHERE id = ?", (json.dumps(brief, ensure_ascii=False), row["id"]))
            handoffs_changed += 1
    conn.commit()

    folder = Path(trace_dir) if trace_dir else trace.trace_dir()
    deleted = 0
    for tid in set(trace_ids):
        if trace.is_valid_trace_id(tid) and (folder / f"{tid}.jsonl").exists():
            (folder / f"{tid}.jsonl").unlink()
            deleted += 1

    return {
        "merchant_id": merchant_id,
        "erased_at": _now(now).strftime(_ISO),
        "anonymised": {"merchants": merchants_changed, "turns": turns_changed, "handoffs": handoffs_changed,
                       "trace_files_deleted": deleted},
        "consents_withdrawn_now": withdrawn,
        "kept": RETAINED,
    }


if __name__ == "__main__":      # python -m chaukas.compliance.retention  -> run the retention sweep once
    from chaukas.db import connect

    _conn = connect()
    try:
        print(json.dumps(purge(_conn), indent=2))
    finally:
        _conn.close()
