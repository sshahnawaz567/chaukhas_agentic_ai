"""[MOCK] raise_ticket, update_ticket, void_ticket (rollback). Writes ticket_events.

Owner: Member 1 · Contract: CONTRACTS C3
"""
from __future__ import annotations

from chaukas import db
from chaukas.core import m2_shim
from chaukas.core.models import RollbackResult, Ticket
from chaukas.integrations._common import deterministic_id, execution_by_token, stored_ref

_ACTOR = "action_agent"


def _event(conn, ticket_id: str, event_type: str, detail: str, session_id: str | None = None) -> None:
    conn.execute(
        "INSERT INTO ticket_events (ticket_id, session_id, actor, actor_id, event_type, detail) VALUES (?,?,?,?,?,?)",
        (ticket_id, session_id, "agent", _ACTOR, event_type, m2_shim.scrub(detail)),
    )


def raise_ticket(merchant_id: str, issue: str, settlement_id: str | None,
                 session_id: str, idempotency_key: str) -> Ticket:
    conn = db.connect()
    try:
        prior = stored_ref(conn, idempotency_key)
        if prior:
            row = conn.execute("SELECT status FROM tickets WHERE id=?", (prior,)).fetchone()
            return Ticket(ticket_id=prior, status=row["status"] if row else "open")
        ticket_id = deterministic_id(conn, "TKT", idempotency_key, "tickets")
        conn.execute(
            "INSERT INTO tickets (id, merchant_id, settlement_id, session_id, issue) VALUES (?,?,?,?,?)",
            (ticket_id, merchant_id, settlement_id, session_id, m2_shim.scrub(issue)),
        )
        _event(conn, ticket_id, "created", issue, session_id)
        conn.commit()
        return Ticket(ticket_id=ticket_id, status="open")
    finally:
        conn.close()


def update_ticket(ticket_id: str, note: str, status: str | None, idempotency_key: str) -> Ticket:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if not row:
            raise ValueError(f"ticket {ticket_id} not found")
        if stored_ref(conn, idempotency_key):  # replay: already applied
            return Ticket(ticket_id=ticket_id, status=row["status"])
        new_status = status or row["status"]
        if new_status != row["status"]:
            conn.execute("UPDATE tickets SET status=? WHERE id=?", (new_status, ticket_id))
            _event(conn, ticket_id, "status_change", f"{row['status']} -> {new_status}")
        _event(conn, ticket_id, "action_taken", note)
        conn.commit()
        return Ticket(ticket_id=ticket_id, status=new_status)
    finally:
        conn.close()


def void_ticket(rollback_token: str) -> RollbackResult:
    """Rollback: a raised ticket is closed (never deleted); an update gets a compensating note."""
    conn = db.connect()
    try:
        ex = execution_by_token(conn, rollback_token)
        if not ex or not ex["result_ref"]:
            return RollbackResult(ok=True, detail="nothing to roll back")
        ticket_id = ex["result_ref"]
        if ex["action_type"] == "raise_ticket":
            conn.execute(
                "UPDATE tickets SET status='closed', resolution='voided by rollback', resolved_by='agent', resolved_at=? WHERE id=?",
                (db.now_iso(), ticket_id),
            )
            _event(conn, ticket_id, "status_change", "closed: voided by rollback")
        else:
            _event(conn, ticket_id, "note", "previous update rolled back")
        conn.commit()
        return RollbackResult(ok=True, detail=f"{ticket_id} rolled back")
    finally:
        conn.close()
