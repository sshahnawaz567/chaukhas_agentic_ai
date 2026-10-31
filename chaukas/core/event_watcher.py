"""Event watcher: finds failed settlements nobody has told the merchant about yet, and starts a proactive
session for each one (orchestrator.handle_event). Deterministic, no LLM, read-only on money state.

- Reads the settlements TABLE, fresh (CLAUDE.md rule 4), never merchant_fixtures.json: after a retrigger the
  row is 'retriggered' while the JSON still says 'failed', so the JSON would notify the merchant forever.
- Only status='failed' is a trigger (v1). 'pending' (bank down, waiting) is not.
- Dedupe: one proactive session per settlement, keyed by sessions.trigger_ref = 'settlement_failed:<id>'.
- Runs on demand only (POST /api/events/scan). Production: a ledger event / Kafka consumer (roadmap).
- Second kind, `device_upgrade` (DEVICE_UPGRADE_PLAN.md): the merchant's own transaction pattern crossed a
  device-advisor threshold. Only `kind="device_upgrade"` runs it, so a settlement scan never sends a sales nudge.
  Pre-filtered with the same gating as the guardrail (support first, cooling-off, consent) so a nudge is never
  sent for something the guardrail would BLOCK; the guardrail still decides. At most one nudge per merchant in
  policy.yaml `device_nudge_every_days`.

Owner: Member 1 · PROACTIVE_FEATURE_CHANGES.md §4.2
"""
from __future__ import annotations

import threading
from typing import Any

from datetime import datetime, timedelta, timezone

from chaukas import db
from chaukas.compliance import consent
from chaukas.core import orchestrator
from chaukas.gateway import session as gw
from chaukas.integrations import devices
from chaukas.integrations._common import load_config

KINDS = ("settlement_failed", "device_upgrade")
_ISO = "%Y-%m-%dT%H:%M:%SZ"

_scan_lock = threading.Lock()  # two clicks at once must not notify the same settlement twice


def trigger_ref(settlement_id: str) -> str:
    return f"settlement_failed:{settlement_id}"


def find_new_failures(merchant_id: str | None = None) -> list[dict[str, str]]:
    """Failed settlements without a proactive session yet. Raises ProactiveSchemaMissing before schema S5."""
    conn = db.connect()
    try:
        if not gw.has_trigger_columns(conn):
            raise gw.ProactiveSchemaMissing("sessions.trigger_source/trigger_ref missing (schema S5)")
        sql = "SELECT id, merchant_id FROM settlements WHERE status='failed'"
        args: tuple = ()
        if merchant_id:
            sql, args = sql + " AND merchant_id=?", (merchant_id,)
        hits = conn.execute(sql + " ORDER BY merchant_id, id", args).fetchall()
        return [{"merchant_id": h["merchant_id"], "settlement_id": h["id"]} for h in hits
                if not conn.execute("SELECT 1 FROM sessions WHERE trigger_ref=?", (trigger_ref(h["id"]),)).fetchone()]
    finally:
        conn.close()


def _device_blocked(conn, merchant_id: str, to_device: str) -> str | None:
    """Why a device nudge must not be sent now (None = clear). Mirrors the guardrail's device gating."""
    policy = load_config("policy")
    now = datetime.now(timezone.utc)
    m = conn.execute("SELECT kyc_status FROM merchants WHERE merchant_id=?", (merchant_id,)).fetchone()
    if m is None or m["kyc_status"] != "verified":
        return "kyc"
    checks = (
        ("open settlement", "SELECT 1 FROM settlements WHERE merchant_id=? AND status IN ('failed','pending')", ()),
        ("open ticket", "SELECT 1 FROM tickets WHERE merchant_id=? AND status IN ('open','in_progress')", ()),
        ("open handoff", "SELECT 1 FROM handoffs WHERE merchant_id=? AND status IN ('open','claimed')", ()),
        ("already requested", "SELECT 1 FROM device_offers WHERE merchant_id=? AND to_device=? AND status='accepted'",
         (to_device,)),
    )
    for why, sql, extra in checks:
        if conn.execute(sql, (merchant_id, *extra)).fetchone():
            return why
    cutoff = (now - timedelta(days=int(policy.get("offer_cooling_off_days", 7)))).strftime(_ISO)
    for table in ("offers", "device_offers"):
        if conn.execute(f"SELECT 1 FROM {table} WHERE merchant_id=? AND status='declined' AND declined_at >= ?",
                        (merchant_id, cutoff)).fetchone():
            return "cooling-off"
    if consent.is_withdrawn(conn, merchant_id, "device_offer"):
        return "consent withdrawn"
    since = (now - timedelta(days=int(policy.get("device_nudge_every_days", 30)))).strftime(_ISO)
    if conn.execute("SELECT 1 FROM sessions WHERE trigger_ref LIKE ? AND created_at >= ?",
                    (f"device_upgrade:{merchant_id}:%", since)).fetchone():
        return "nudged recently"
    return None


def find_device_candidates(merchant_id: str | None = None) -> list[dict[str, str]]:
    """Merchants whose transaction pattern crossed a device-advisor threshold and who may be nudged now."""
    conn = db.connect()
    try:
        if not gw.has_trigger_columns(conn):
            raise gw.ProactiveSchemaMissing("sessions.trigger_source/trigger_ref missing (schema S5)")
        sql, args = "SELECT merchant_id FROM merchants", ()
        if merchant_id:
            sql, args = sql + " WHERE merchant_id=?", (merchant_id,)
        ids = [r["merchant_id"] for r in conn.execute(sql + " ORDER BY merchant_id", args).fetchall()]
        out = []
        for mid in ids:
            advice = devices.advise(mid)
            if advice.recommended and not _device_blocked(conn, mid, advice.to_device):
                out.append({"merchant_id": mid, "to_device": advice.to_device})
        return out
    finally:
        conn.close()


def scan(merchant_id: str | None = None, kind: str = "settlement_failed") -> list[dict[str, Any]]:
    """settlement_failed: notify every new failure -> [{merchant_id, settlement_id, session_id, turn}].
    device_upgrade: nudge every merchant who crossed a device threshold -> [{merchant_id, to_device, session_id, turn}]."""
    if kind not in KINDS:
        raise ValueError(f"unknown scan kind {kind!r}")
    with _scan_lock:
        out = []
        if kind == "device_upgrade":
            for hit in find_device_candidates(merchant_id):
                turn = orchestrator.handle_device_event(hit["merchant_id"], hit["to_device"])
                out.append({**hit, "session_id": turn.session_id, "turn": turn})
            return out
        for hit in find_new_failures(merchant_id):
            turn = orchestrator.handle_event(hit["merchant_id"], hit["settlement_id"])
            out.append({**hit, "session_id": turn.session_id, "turn": turn})
        return out
