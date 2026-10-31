"""Handoff agent: builds HandoffBrief (1 LLM call for wording), writes handoffs row.
Never dumps the transcript.

The structured parts (verified / done / refused / reason / confidence / suggested step) are built
deterministically from state. The LLM only words `asked`, and `decision_needed` ONLY when a step is pending
(the human approves that exact step). Every LLM line passes `_safe_line()`: an amount that is not in the plan
or the ledger, or an "approve / transfer / send" with no pending step, rejects it -> the deterministic wording
below. A suspected prompt injection gets a brief written entirely by code (`injection_brief`).

Owner: Member 1 · Contract: CONTRACTS C1
"""
from __future__ import annotations

import json
import re
from typing import Literal

from chaukas import db
from chaukas.agents.schemas import HandoffOutput
from chaukas.core import m2_shim
from chaukas.core.models import (
    ActionType,
    ConversationState,
    HandoffBrief,
    HandoffReason,
    ReasonCode,
)
from chaukas.llm.client import LLMResult, LLMUnavailable
from chaukas.llm.prompt import LLMOutputError, esc, run_validated, to_xml

_DONE_LABEL = {
    ActionType.RETRIGGER_PAYOUT.value: "payout re-sent ({ref})",
    ActionType.RAISE_TICKET.value: "ticket {ref} raised",
    ActionType.UPDATE_TICKET.value: "ticket {ref} updated",
    ActionType.CREATE_OFFER.value: "loan offer {ref} accepted by merchant",
}


def _verified(state: ConversationState) -> list[str]:
    ctx = state.merchant
    facts: list[str] = []
    if ctx is None:
        return facts
    for s in ctx.settlements:
        if s.status in ("failed", "pending", "retriggered"):
            line = f"{s.id} {s.status}" + (f", {s.cause}" if s.cause else "")
            facts.append(line)
            if s.cause == "IFSC_MISMATCH":
                facts.append("bank details updated after failure" if s.retriggerable
                             else "bank details NOT updated since the failure")
            if any(p.action_type == ActionType.RETRIGGER_PAYOUT.value and p.amount == s.amount for p in state.plan):
                facts.append(f"amount {s.amount} matches ledger")
    facts.append(f"KYC {ctx.kyc_status}")
    return facts


def _done(state: ConversationState) -> list[str]:
    return [_DONE_LABEL[r.action_type].format(ref=r.ref_id) for r in state.completed
            if r.status == "success" and r.action_type in _DONE_LABEL]


def _wording(state: ConversationState, reason: str) -> tuple[str, str]:
    """Deterministic fallback for the two LLM-worded lines."""
    step = state.pending_step
    amount = f"₹{step.amount:,}" if step and step.amount else None
    intent = state.intent.value if state.intent else "unknown"
    if reason in (ReasonCode.OVER_AUTO_LIMIT.value, ReasonCode.OVER_DAILY_LIMIT.value) and amount:
        return (f"Merchant wants the failed settlement of {amount} sent",
                f"Approve retrigger of {amount} to the merchant's registered account?")
    table = {
        HandoffReason.KYC_PENDING.value: ("Merchant's settlement is held because KYC is pending",
                                          "Should KYC follow-up be started for this merchant?"),
        HandoffReason.BANK_DETAILS_NOT_UPDATED.value: (
            "Merchant's settlement failed on bank details that are still not updated",
            "Should the team contact the merchant to update bank details?"),
        HandoffReason.OUT_OF_SCOPE.value: ("Merchant asked for a refund (no refund tool, by design)",
                                           "Should this refund request be processed manually?"),
        HandoffReason.HUMAN_REQUESTED.value: ("Merchant asked to speak to a human",
                                              "Please contact the merchant: which team member takes this?"),
        HandoffReason.ACTION_FAILED.value: ("Merchant's request could not be completed (tool error, rolled back)",
                                            "Should the failed action be retried manually?"),
        HandoffReason.MERCHANT_DECLINED_STEP_UP.value: ("Merchant declined the extra verification step",
                                                        "Should the team follow up with the merchant?"),
        HandoffReason.LOW_CONFIDENCE.value: (f"Message unclear (best guess: {intent})",
                                             "What does the merchant need?"),
        HandoffReason.UNKNOWN_INTENT.value: ("Message not understood", "What does the merchant need?"),
    }
    return table.get(reason, (f"Merchant request ({intent})", "How should this be resolved?"))


def _llm_wording(state: ConversationState, reason: str, verified, done, refused
                 ) -> tuple[tuple[str, str] | None, LLMResult | None]:
    ctx = to_xml("handoff_context", {
        "reason": reason, "intent": state.intent.value if state.intent else None,
        "verified": verified, "done": done,
        "refused": [f"{r.action_type}: {r.reason}" for r in refused] or None,
        "pending_action": (f"{state.pending_step.action_type} of {state.pending_step.amount}"
                           if state.pending_step and state.pending_step.amount else None),
    })
    variables = {"context": ctx, "user_question": esc(state.message_masked)}
    key = f"handoff|{state.merchant_id}|{state.message_masked}|{reason}"
    try:
        out, llm = run_validated("handoff", "handoff.v1.txt", variables, HandoffOutput, replay_key=key)
        r = out.handoff_result
        return (r.asked, r.decision_needed), llm
    except (LLMUnavailable, LLMOutputError):
        return None, None


_AMOUNT = re.compile(r"(?:₹|\brs\.?|\binr)\s*([\d,]+)|(?<![\w\-/])(\d{1,3}(?:,\d{2,3})+|\d{3,})(?![\w\-/])", re.I)
_MONEY_VERB = re.compile(r"\b(approv\w*|transfer\w*|send\w*|sent|pay\w*|re-?trigger\w*|re-?send\w*|disburs\w*|"
                         r"credit\w*|refund\w*|release\w*|remit\w*)\b", re.I)


def _amounts(text: str) -> set[int]:
    out = set()
    for m in _AMOUNT.finditer(text):
        digits = (m.group(1) or m.group(2) or "").replace(",", "")
        if digits.isdigit():
            out.add(int(digits))
    return out


def _safe_line(line: str, state: ConversationState, *, money_verbs_ok: bool) -> bool:
    """Deterministic check on an LLM-worded line. Amounts must come from the plan or the ledger (never from
    the merchant's message); money verbs only when a step is actually pending for the human to approve."""
    known = {p.amount for p in state.plan if p.amount}
    if state.pending_step and state.pending_step.amount:
        known.add(state.pending_step.amount)
    if state.merchant:
        known |= {s.amount for s in state.merchant.settlements}
    if _amounts(line) - known:
        return False
    return money_verbs_ok or not _MONEY_VERB.search(line)


def injection_brief(state: ConversationState, signals: list[str]) -> HandoffBrief:
    """Fraud-review brief for a suspected prompt injection. Written by code only: an LLM that would obey the
    injection never words it. No amount from the message, no suggested step, nothing to approve."""
    ctx = state.merchant
    open_issues = [s for s in (ctx.settlements if ctx else []) if s.status in ("failed", "pending")]
    verified = ([f"{s.id} {s.status}" + (f", {s.cause}" if s.cause else "") for s in open_issues]
                or ["No failed/pending settlement: the ledger shows nothing owed"])
    if ctx:
        verified.append(f"KYC {ctx.kyc_status}")
    verified.append("Injection signals: " + ", ".join(signals))
    return HandoffBrief(
        asked="Message contains instructions aimed at the AI (possible prompt injection) and asks for a money transfer",
        verified=verified, done=_done(state), refused=list(state.refused),
        reason_code=HandoffReason.SUSPECTED_INJECTION.value, confidence=1.0,
        decision_needed="Review for fraud: no money action is pending", suggested_step=None,
    )


def build(state: ConversationState, reason_code: str,
          confirmation_kind: Literal["consent", "step_up"] | None = None,
          pending_audit_id: int | None = None) -> tuple[HandoffBrief, LLMResult | None]:
    verified, done = _verified(state), _done(state)
    asked, decision = _wording(state, reason_code)
    wording, llm = _llm_wording(state, reason_code, verified, done, state.refused)
    if wording:
        llm_asked, llm_decision = wording
        if _safe_line(llm_asked, state, money_verbs_ok=True):
            asked = llm_asked
        # decision_needed from the LLM only when a step is pending: the human approves THAT step. Otherwise the
        # fixed line, so the merchant's demand can never be turned into "Approve the transfer of ...?"
        if state.pending_step is not None and _safe_line(llm_decision, state, money_verbs_ok=True):
            decision = llm_decision
    suggested = state.pending_step.model_copy() if state.pending_step else None
    brief = HandoffBrief(
        asked=m2_shim.mask_text(asked), verified=verified, done=done, refused=list(state.refused),
        reason_code=reason_code, confidence=round(state.intent_confidence or 0.5, 2),
        decision_needed=m2_shim.mask_text(decision), suggested_step=suggested,
        pending_audit_id=pending_audit_id, confirmation_kind=confirmation_kind,
    )
    return brief, llm


def save(state: ConversationState, brief: HandoffBrief) -> str:
    """Insert the handoffs row (brief scrubbed). Reuses an open handoff of the same session+reason."""
    conn = db.connect()
    try:
        existing = conn.execute(
            "SELECT id FROM handoffs WHERE session_id=? AND reason_code=? AND status='open'",
            (state.session_id, brief.reason_code)).fetchone()
        if existing:
            return existing["id"]
        n = conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] + 1
        handoff_id = f"HO-{n:05d}"
        while conn.execute("SELECT 1 FROM handoffs WHERE id=?", (handoff_id,)).fetchone():
            n += 1
            handoff_id = f"HO-{n:05d}"
        ticket_id = next((r.ref_id for r in state.completed
                          if r.status == "success" and r.action_type in ("raise_ticket", "update_ticket")), None)
        conn.execute(
            """INSERT INTO handoffs (id, session_id, merchant_id, ticket_id, trace_id, reason_code,
                   brief_json, confidence, decision_needed) VALUES (?,?,?,?,?,?,?,?,?)""",
            (handoff_id, state.session_id, state.merchant_id, ticket_id, state.trace_id, brief.reason_code,
             json.dumps(m2_shim.scrub(brief.model_dump(mode="json")), ensure_ascii=False),
             brief.confidence, brief.decision_needed),
        )
        if ticket_id:
            conn.execute(
                "INSERT INTO ticket_events (ticket_id, session_id, trace_id, actor, actor_id, event_type, detail) "
                "VALUES (?,?,?,?,?,?,?)",
                (ticket_id, state.session_id, state.trace_id, "agent", "handoff_agent", "handoff",
                 m2_shim.scrub(f"handed to human: {brief.reason_code}")),
            )
        conn.commit()
        return handoff_id
    finally:
        conn.close()
