"""Append-only audit_log inserts; executions insert/update (pending -> success|failed|rolled_back).

Owner: Member 2 · Contract: schema.sql audit_log + executions

Two tables, two jobs:
  audit_log  = what the deterministic guardrail DECIDED. Insert only (DB triggers refuse UPDATE/DELETE).
  executions = what was actually RUN. Mutable state, and the idempotency ledger.
Every value written here goes through scrub() first, so no raw PII reaches the DB.
"""
import json
import sqlite3
from typing import Any

from chaukas.db import execute, now_iso, query_one
from chaukas.privacy.scrub import scrub

_TRANSITIONS = {
    "pending": {"success", "failed", "rolled_back"},
    "success": {"rolled_back"},
    "failed": {"rolled_back"},
    "rolled_back": set(),
}


def params_masked(params: Any) -> str:
    """The one serialisation of a step's params (scrubbed, key-sorted).
    audit_log.params_masked is written with it, and the guardrail compares against it to check
    that a confirmation is for the identical step."""
    return json.dumps(scrub(params), sort_keys=True, ensure_ascii=False)


def record_decision(
    conn: sqlite3.Connection, *, trace_id: str, session_id: str | None, merchant_id: str,
    actor: str, step_no: int | None, action_type: str, amount: int | None, params: Any,
    guardrail_decision: str, reason_code: str, reason: str,
    rollback_token: str | None = None, confirms_audit_id: int | None = None,
    ticket_id: str | None = None,
) -> int:
    """Insert one audit_log row and commit it right away. Returns the new audit id."""
    cur = execute(
        conn,
        """INSERT INTO audit_log (trace_id, session_id, ticket_id, ts, merchant_id, actor, step_no,
               action_type, amount, params_masked, guardrail_decision, reason_code, reason,
               rollback_token, confirms_audit_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (trace_id, session_id, ticket_id, now_iso(), merchant_id, actor, step_no, action_type,
         amount, params_masked(params), guardrail_decision, reason_code, scrub(reason),
         rollback_token, confirms_audit_id),
    )
    conn.commit()
    return cur.lastrowid


def start_execution(
    conn: sqlite3.Connection, *, idempotency_key: str, audit_id: int, trace_id: str,
    session_id: str | None, merchant_id: str, action_type: str, amount: int | None,
) -> None:
    """Insert the 'pending' executions row BEFORE the tool is called.
    The DB trigger rejects it unless audit_id points to an ALLOW row; rollback_token is read from that row."""
    row = query_one(conn, "SELECT rollback_token FROM audit_log WHERE id = ?", (audit_id,))
    execute(
        conn,
        """INSERT INTO executions (idempotency_key, audit_id, trace_id, session_id, merchant_id,
               action_type, amount, rollback_token, status) VALUES (?,?,?,?,?,?,?,?, 'pending')""",
        (idempotency_key, audit_id, trace_id, session_id, merchant_id, action_type, amount,
         row["rollback_token"] if row else None),
    )
    conn.commit()


def finish_execution(
    conn: sqlite3.Connection, idempotency_key: str, status: str,
    result_ref: str | None = None, error: str | None = None,
) -> None:
    """Move an execution to success / failed / rolled_back. Illegal moves raise ValueError."""
    current = get_execution(conn, idempotency_key)
    if current is None:
        raise KeyError(f"no execution for key {idempotency_key!r}")
    if status not in _TRANSITIONS[current["status"]]:
        raise ValueError(f"execution cannot go {current['status']} -> {status}")
    execute(
        conn,
        "UPDATE executions SET status = ?, result_ref = COALESCE(?, result_ref), error = ?, updated_at = ? "
        "WHERE idempotency_key = ?",
        (status, result_ref, scrub(error) if error else None, now_iso(), idempotency_key),
    )
    conn.commit()


def get_execution(conn: sqlite3.Connection, idempotency_key: str) -> sqlite3.Row | None:
    return query_one(conn, "SELECT * FROM executions WHERE idempotency_key = ?", (idempotency_key,))
