"""Action agent: executes an ALLOWed step via integrations/*, idempotent,
rollback on failure. Only place that calls privacy.detokenise().

Invariant: `run()` refuses any decision that is not ALLOW. The `executions_require_allow` DB trigger
is the second lock.

Owner: Member 1 · Contract: CONTRACTS C3
"""
from __future__ import annotations

import time

from chaukas import db
from chaukas.core import m2_shim
from chaukas.core.models import (
    ActionResult,
    ActionType,
    ConversationState,
    Decision,
    PlannedStep,
    ReasonCode,
    Verdict,
)
from chaukas.integrations import lending, payments, ticketing

_READ_ONLY = {ActionType.VERIFY_LEDGER.value, ActionType.CHECK_ELIGIBILITY.value}

_ROLLBACK = {
    ActionType.RETRIGGER_PAYOUT.value: payments.cancel_payout,
    ActionType.RAISE_TICKET.value: ticketing.void_ticket,
    ActionType.UPDATE_TICKET.value: ticketing.void_ticket,
    ActionType.CREATE_OFFER.value: lending.withdraw_offer,
}


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def prior_result(idempotency_key: str, step: PlannedStep) -> ActionResult | None:
    """The earlier ActionResult for this key (replayed=True), or None if it never ran."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM executions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    status = row["status"] if row["status"] in ("success", "rolled_back") else "failed"
    return ActionResult(step_no=step.step_no, action_type=step.action_type, status=status,
                        ref_id=row["result_ref"], replayed=True, error=row["error"],
                        audit_id=row["audit_id"], latency_ms=0)


def run(step: PlannedStep, state: ConversationState, decision: Decision, *,
        kfs_shown_at: str | None = None) -> ActionResult:
    """Execute one step. Raises PermissionError if `decision` is not an ALLOW."""
    if decision.verdict != Verdict.ALLOW:
        raise PermissionError(f"action.run refused: guardrail verdict is {decision.verdict.value}")
    t0 = time.perf_counter()

    if step.action_type in _READ_ONLY:
        return _run_read_only(step, state, t0)

    if decision.audit_id is None or not decision.rollback_token:
        raise PermissionError("write action needs an audited ALLOW with a rollback token")

    key = step.idempotency_key
    earlier = prior_result(key, step)
    if earlier is not None:  # idempotent replay: never a second payout / ticket / offer
        return earlier

    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO executions (idempotency_key, audit_id, trace_id, session_id, merchant_id,
                   action_type, amount, rollback_token, status) VALUES (?,?,?,?,?,?,?,?, 'pending')""",
            (key, decision.audit_id, state.trace_id, state.session_id, state.merchant_id,
             step.action_type, step.amount, decision.rollback_token),
        )
        conn.commit()  # 'pending' row exists BEFORE the tool call (counts towards the daily limit)

        try:
            ref = _call_tool(step, state, decision, key, kfs_shown_at)
            if ref is None:
                raise RuntimeError("tool returned no reference")
        except Exception as exc:  # tool error -> rollback -> handoff ACTION_FAILED (orchestrator)
            err = m2_shim.mask_text(str(exc))[:200]
            rb = _ROLLBACK[step.action_type](decision.rollback_token)
            conn.execute("UPDATE executions SET status=?, error=?, updated_at=? WHERE idempotency_key=?",
                         ("rolled_back" if rb.ok else "failed", err, db.now_iso(), key))
            conn.commit()
            return ActionResult(step_no=step.step_no, action_type=step.action_type,
                                status="rolled_back" if rb.ok else "failed", error=err,
                                audit_id=decision.audit_id, latency_ms=_ms(t0))

        conn.execute("UPDATE executions SET status='success', result_ref=?, updated_at=? WHERE idempotency_key=?",
                     (ref, db.now_iso(), key))
        conn.commit()
        return ActionResult(step_no=step.step_no, action_type=step.action_type, status="success",
                            ref_id=ref, audit_id=decision.audit_id, latency_ms=_ms(t0))
    finally:
        conn.close()


def _run_read_only(step: PlannedStep, state: ConversationState, t0: float) -> ActionResult:
    try:
        if step.action_type == ActionType.VERIFY_LEDGER.value:
            ledger = payments.verify_ledger(step.params["settlement_id"])
            if not ledger.found:
                raise LookupError("settlement not found")
        else:
            product = step.params.get("product", "term_loan")
            decision = lending.check_eligibility(step.params["merchant_id"], product)
            if state.merchant is not None:  # each product's answer in its own slot (guardrail check 7 reads it)
                if product == "credit_line":
                    state.merchant.credit_line = decision
                else:
                    state.merchant.eligibility = decision
        return ActionResult(step_no=step.step_no, action_type=step.action_type, status="success",
                            latency_ms=_ms(t0))
    except Exception as exc:
        return ActionResult(step_no=step.step_no, action_type=step.action_type, status="failed",
                            error=m2_shim.mask_text(str(exc))[:200], latency_ms=_ms(t0))


def _call_tool(step: PlannedStep, state: ConversationState, decision: Decision, key: str,
               kfs_shown_at: str | None) -> str | None:
    p = step.params
    if step.action_type == ActionType.RETRIGGER_PAYOUT.value:
        # the ONLY detokenise() in the codebase: payout account resolved from merchant_id, never a param
        account = m2_shim.detokenise(state.merchant.account_ref)
        out = payments.retrigger_payout(p["settlement_id"], p["amount"], account, key)
        if out.status != "success":
            raise RuntimeError(out.error or "payout failed")
        return out.payout_ref
    if step.action_type == ActionType.RAISE_TICKET.value:
        return ticketing.raise_ticket(p["merchant_id"], p["issue"], p.get("settlement_id"),
                                      state.session_id, key).ticket_id
    if step.action_type == ActionType.UPDATE_TICKET.value:
        return ticketing.update_ticket(p["ticket_id"], p["note"], p.get("status"), key).ticket_id
    if step.action_type == ActionType.CREATE_OFFER.value:
        if decision.reason_code != ReasonCode.CONFIRMED_BY_MERCHANT:
            raise PermissionError("an offer needs the MERCHANT's own consent")  # a human cannot consent for them
        kfs = lending.build_kfs(p["merchant_id"], p["amount"], p.get("product", "term_loan"))
        return lending.create_offer(p["merchant_id"], p["amount"], True, kfs, state.session_id, key,
                                    kfs_shown_at=kfs_shown_at, trace_id=state.trace_id).offer_id
    raise ValueError(f"unsupported action {step.action_type}")
