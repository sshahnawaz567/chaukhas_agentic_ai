"""Guardrail agent: check(step, state, confirmation=None) -> Decision.
Deterministic, no LLM. Writes one audit_log row per write action.

Owner: Member 2 · Contract: CONTRACTS C2

This file is the thin shell. The 10 checks live in chaukas/policy/engine.py.
It turns the engine's Outcome into a Decision and writes the audit row.
"""
import sqlite3
import uuid
from datetime import datetime

from chaukas.core.models import ConversationState, Confirmation, Decision, PlannedStep, Verdict
from chaukas.db import connect
from chaukas.observability import audit
from chaukas.policy import engine


def check(
    step: PlannedStep, state: ConversationState, confirmation: Confirmation | None = None,
    *, conn: sqlite3.Connection | None = None, policy: dict | None = None,
    now: datetime | None = None, actor: str | None = None,
) -> Decision:
    """Decide ALLOW / BLOCK / NEEDS_CONFIRMATION for one planned step.

    Keyword-only extras are additive: `conn` (tests), `policy` (tests), `now` (tests),
    `actor` (e.g. 'system' for /api/redteam/check). Normal callers pass only the three contract arguments.
    """
    own_conn = conn is None
    conn = conn or connect()
    try:
        policy = policy or engine.load_policy()
        mock_otp = engine.load_mock_otp() if confirmation else None
        out = engine.evaluate(step, state, conn, policy, confirmation, now, mock_otp)

        kind = out.confirmation_kind
        if out.verdict is Verdict.ALLOW and step.action_type in policy["read_only_actions"]:
            # read-only and allowed: traced by the caller, not audited (blocked read-only IS audited)
            return Decision(verdict=out.verdict, reason_code=out.reason_code, reason=out.reason,
                            audit_id=None, rollback_token=None)

        rollback_token = f"rb_{uuid.uuid4().hex}" if out.verdict is Verdict.ALLOW else None
        ticket_id = step.params.get("ticket_id") if isinstance(step.params.get("ticket_id"), str) else None
        audit_id = audit.record_decision(
            conn, trace_id=state.trace_id, session_id=state.session_id, merchant_id=state.merchant_id,
            actor=out.confirm_actor or actor or "agent", step_no=step.step_no, action_type=step.action_type,
            amount=out.amount, params=step.params, guardrail_decision=out.verdict.value,
            reason_code=out.reason_code.value, reason=out.reason, rollback_token=rollback_token,
            confirms_audit_id=out.confirms_audit_id, ticket_id=ticket_id,
        )
        return Decision(verdict=out.verdict, reason_code=out.reason_code, reason=out.reason,
                        audit_id=audit_id, rollback_token=rollback_token, confirmation_kind=kind)
    finally:
        if own_conn:
            conn.close()
