"""Consent artefacts (table `consents`): grant / withdraw / check per purpose
('ai_assistance', 'loan_offer'). Withdrawal is as easy as giving consent.
Loan-offer consent is only valid after the KFS (key fact statement) was shown.

Owner: Member 2 · COMPLIANCE.md D3, D4, L1

The table is append-only history: one row per grant or withdrawal. The LATEST row per
(merchant_id, purpose) is the current state. We never UPDATE or DELETE a consent row (CLAUDE.md rule 6).
"""
import sqlite3
from typing import Literal

from chaukas.compliance import disclosure
from chaukas.db import execute, query_one

PURPOSES = ("ai_assistance", "loan_offer")
Purpose = Literal["ai_assistance", "loan_offer"]
Action = Literal["granted", "withdrawn"]


class ConsentError(ValueError):
    """The consent request itself is invalid (unknown purpose, or loan consent before the KFS was shown)."""


def _latest(conn: sqlite3.Connection, merchant_id: str, purpose: str) -> sqlite3.Row | None:
    # ORDER BY id, not created_at: two rows in the same second must still order correctly
    return query_one(conn, "SELECT * FROM consents WHERE merchant_id = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
                     (merchant_id, purpose))


def record(
    conn: sqlite3.Connection, merchant_id: str, purpose: str, action: str, *,
    channel: str | None = "chat", session_id: str | None = None, kfs_shown: bool = False,
) -> int:
    """Append one consent row and return its id.

    No-op when nothing changes (same action, same notice version as the latest row): the id of that
    existing row is returned, so a double-click does not pollute the history.
    `kfs_shown` must be True to GRANT loan_offer consent: the Key Fact Statement has to be shown first (RBI L1).
    """
    if purpose not in PURPOSES:
        raise ConsentError(f"unknown purpose {purpose!r}")
    if action not in ("granted", "withdrawn"):
        raise ConsentError(f"unknown action {action!r}")
    if purpose == "loan_offer" and action == "granted" and not kfs_shown:
        raise ConsentError("loan_offer consent is only valid after the KFS was shown")

    version = disclosure.notice_version()
    latest = _latest(conn, merchant_id, purpose)
    if latest and latest["action"] == action and latest["notice_version"] == version:
        return latest["id"]

    cur = execute(
        conn,
        "INSERT INTO consents (merchant_id, purpose, action, notice_version, channel, session_id) "
        "VALUES (?,?,?,?,?,?)",
        (merchant_id, purpose, action, version, channel, session_id),
    )
    conn.commit()
    return cur.lastrowid


def grant(conn: sqlite3.Connection, merchant_id: str, purpose: str, **kw) -> int:
    return record(conn, merchant_id, purpose, "granted", **kw)


def withdraw(conn: sqlite3.Connection, merchant_id: str, purpose: str, **kw) -> int:
    return record(conn, merchant_id, purpose, "withdrawn", **kw)


def has_consent(conn: sqlite3.Connection, merchant_id: str, purpose: str) -> bool:
    """True only if the latest row for this purpose is a grant. Never asked, or withdrawn -> False."""
    latest = _latest(conn, merchant_id, purpose)
    return bool(latest and latest["action"] == "granted")


def is_withdrawn(conn: sqlite3.Connection, merchant_id: str, purpose: str) -> bool:
    """True only if the merchant EXPLICITLY withdrew (latest row is 'withdrawn'). Never asked -> False:
    that case is handled by the per-offer consent question (guardrail check 10), not by a block."""
    latest = _latest(conn, merchant_id, purpose)
    return bool(latest and latest["action"] == "withdrawn")


def current_state(conn: sqlite3.Connection, merchant_id: str) -> dict[str, dict]:
    """Current state per purpose: {'state': 'granted'|'withdrawn'|None, 'notice_version', 'at', 'id'}."""
    out = {}
    for purpose in PURPOSES:
        row = _latest(conn, merchant_id, purpose)
        out[purpose] = (
            {"state": row["action"], "notice_version": row["notice_version"], "at": row["created_at"], "id": row["id"]}
            if row else {"state": None, "notice_version": None, "at": None, "id": None}
        )
    return out


def history(conn: sqlite3.Connection, merchant_id: str) -> list[dict]:
    """The full append-only trail, oldest first."""
    rows = conn.execute("SELECT * FROM consents WHERE merchant_id = ? ORDER BY id", (merchant_id,)).fetchall()
    return [dict(r) for r in rows]
