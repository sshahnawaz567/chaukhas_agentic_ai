"""Turn state machine: intent -> context -> plan -> (guardrail -> action | pending | handoff) -> reply.
Invariant: no path reaches action.run() without an ALLOW from guardrail.check().

Owner: Member 1 · Contract: CONTRACTS C1.4
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from chaukas import db
from chaukas.agents import action, context, handoff, intent as intent_agent, notify, reply as reply_agent
from chaukas.compliance import consent
from chaukas.core import create_logs, m2_shim, plans
from chaukas.core.models import (
    ActionResult,
    ActionType,
    Channel,
    Confirmation,
    ConversationState,
    Decision,
    HandoffBrief,
    HandoffReason,
    Intent,
    LoanFollowUp,
    MerchantContext,
    Mode,
    PlannedStep,
    ReasonCode,
    RefusedStep,
    SettlementView,
    Track,
    TurnResponse,
    TurnStatus,
    Urgency,
    Verdict,
)
from chaukas.gateway import session as gw
from chaukas.integrations import insurance, lending
from chaukas.integrations._common import load_config
from chaukas.llm.client import LLMResult

log = logging.getLogger("chaukas.orchestrator")

_OUTCOME = {
    TurnStatus.COMPLETED: "resolved_autonomously",
    TurnStatus.AWAITING_CONFIRMATION: "needs_confirmation",
    TurnStatus.HANDED_OFF: "handoff",
    TurnStatus.FAILED: "failed",
}


class PendingMismatch(ValueError):
    """The confirm request does not point at the session's pending step."""


class ProactiveConsentViolation(RuntimeError):
    """The guardrail ALLOWed a money action in a proactive session without the merchant's yes. Never executed."""


def _proactive_consent_actions() -> set[str]:
    # S6 (policy.yaml, Member 2). Until it lands: the two money actions of PROACTIVE_FEATURE_CHANGES §1.
    return set(load_config("policy").get("proactive_consent_required")
               or [ActionType.RETRIGGER_PAYOUT.value, ActionType.CREATE_OFFER.value])


class _Turn:
    """Per-turn bookkeeping: state, trace spans, cost."""

    def __init__(self, state: ConversationState):
        self.state = state
        self.spans: list[dict[str, Any]] = []
        self.loan_brief: HandoffBrief | None = None  # LOAN_ACCEPTED follow-up, attached in _finish() after the reply
        # proactive flow (event watcher): the trigger, e.g. "settlement_failed:SET-99213"; None = merchant-initiated
        self.proactive_ref: str | None = None
        self.is_event = False  # this turn was started by an event, not a merchant message (no merchant turn row)
        self.notify = False  # reply with the deterministic notification template instead of the reply agent
        self.notify_variant: str | None = None
        self.notify_settlement: SettlementView | None = None
        self.fixed_reply_key: str | None = None  # deterministic reply template (e.g. suspected injection)
        self.cost = 0.0
        self.t0 = time.perf_counter()

    def span(self, agent: str, inp: str, out: str, t_start: float, *, status: str = "ok",
             step_no: int | None = None, llm: LLMResult | None = None) -> None:
        s = self.state
        span = {
            "trace_id": s.trace_id, "session_id": s.session_id, "turn_no": s.turn_no, "seq": len(self.spans) + 1,
            "agent": agent, "step_no": step_no, "input_summary": inp[:240], "output_summary": out[:240],
            "status": status, "latency_ms": int((time.perf_counter() - t_start) * 1000),
            "model": llm.model if llm else None, "tokens_in": llm.tokens_in if llm else 0,
            "tokens_out": llm.tokens_out if llm else 0, "cost_inr": llm.cost_inr if llm else 0.0,
            "ts": db.now_iso(),
        }
        if llm:
            self.cost += llm.cost_inr
        self.spans.append(span)
        m2_shim.emit_span(span)

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def _policy_threshold() -> float:
    return float(load_config("policy").get("intent_confidence_threshold", 0.7))


def _new_state(session: dict, message_masked: str) -> ConversationState:
    return ConversationState(
        session_id=session["session_id"], turn_no=gw.next_turn_no(session["session_id"]),
        trace_id="T-" + uuid.uuid4().hex[:12], merchant_id=session["merchant_id"],
        channel=Channel(session["channel"] or "chat"), mode=Mode(session["mode"] or "autonomous"),
        message_masked=message_masked, history=gw.history(session["session_id"]),
    )


def _stamp(step: PlannedStep, session_id: str) -> PlannedStep:
    step.session_id = session_id
    return step


def _decision_row(step: PlannedStep, d: Decision) -> dict:
    return {"step_no": step.step_no, "action_type": step.action_type, "verdict": d.verdict.value,
            "reason_code": d.reason_code.value, "reason": d.reason, "audit_id": d.audit_id}


# --------------------------------------------------------------------------
# public entry points
# --------------------------------------------------------------------------
def handle_message(session_id: str, text: str) -> TurnResponse:
    session = gw.load_session(session_id)
    state = _new_state(session, gw.mask_incoming(text))
    turn = _Turn(state)
    pending = gw.load_pending(session)
    with create_logs.turn_scope(state.session_id, state.turn_no, state.trace_id):
        try:
            signals = intent_agent.injection_signals(state.message_masked)
            if signals:  # checked in code BEFORE any LLM sees the message (a pending step expires, C1.4)
                _injection_flow(turn, signals)
            else:
                _understand(turn, pending is not None)
                if pending is not None and state.intent in (Intent.CONFIRM, Intent.DENY):
                    _load_context(turn)
                    _resume(turn, pending, approve=state.intent == Intent.CONFIRM, actor="merchant",
                            actor_id=None, kind=None, otp=None)
                else:
                    _fresh_flow(turn)
        except Exception as exc:  # a turn must never crash the API; surface it as FAILED + handoff text
            log.exception("turn failed")
            state.status = TurnStatus.FAILED
            state.errors.append(m2_shim.mask_text(f"{type(exc).__name__}: {exc}")[:200])
        return _finish(turn)


def handle_confirm(session_id: str, pending_audit_id: int | None, approve: bool, kind: str | None,
                   otp: str | None, actor: str, actor_id: str | None) -> TurnResponse:
    """Confirm / deny button. Same code path as a typed 'haan' (CONTRACTS C5)."""
    session = gw.load_session(session_id)
    pending = gw.load_pending(session)
    if pending is None:
        raise PendingMismatch("no pending step in this session")
    if pending_audit_id is not None and pending[2] is not None and pending_audit_id != pending[2]:
        raise PendingMismatch("pending_audit_id does not match the session's pending step")
    label = "[button] confirm" if approve else "[button] deny"
    state = _new_state(session, label)
    state.intent = Intent.CONFIRM if approve else Intent.DENY
    state.intent_confidence = 1.0
    state.lang = session.get("lang")
    state.track, state.urgency = Track.SUPPORT, Urgency.LOW
    turn = _Turn(state)
    with create_logs.turn_scope(state.session_id, state.turn_no, state.trace_id):
        try:
            _load_context(turn)
            _resume(turn, pending, approve=approve, actor=actor, actor_id=actor_id, kind=kind, otp=otp)
        except Exception as exc:
            log.exception("confirm failed")
            state.status = TurnStatus.FAILED
            state.errors.append(m2_shim.mask_text(f"{type(exc).__name__}: {exc}")[:200])
        return _finish(turn)


def handle_event(merchant_id: str, settlement_id: str) -> TurnResponse:
    """Proactive entry point (event watcher): Chaukas speaks first about a failed settlement.

    Same house, second door: context, plan templates, guardrail and action are the reactive ones. Only the
    start differs: the watcher creates the session (trigger_source='proactive'), the intent is known, and the
    reply is a deterministic notification. Money never moves in this turn: the guardrail parks the payout
    for the merchant's yes (Member 2, check 10), and _execute() refuses to run one if it does not.
    """
    trigger_ref = f"settlement_failed:{settlement_id}"
    created = gw.create_session(merchant_id, "chat", "autonomous", trigger_source="proactive",
                                trigger_ref=trigger_ref)
    session = gw.load_session(created["session_id"])
    state = _new_state(session, f"[event] settlement_failed {settlement_id}")  # a marker, no PII
    state.intent, state.intent_confidence = Intent.SETTLEMENT_DELAY, 1.0
    state.lang = session.get("lang")
    state.track, state.urgency = Track.SUPPORT, Urgency.HIGH
    turn = _Turn(state)
    turn.proactive_ref, turn.is_event, turn.notify = trigger_ref, True, True
    with create_logs.turn_scope(state.session_id, state.turn_no, state.trace_id):
        try:
            # "gateway" until Member 2 adds "watcher" to Span.agent (S4): /api/traces validates the literal
            turn.span("gateway", f"watcher: {trigger_ref}", f"proactive session {state.session_id}",
                      time.perf_counter())
            _load_context(turn)
            turn.notify_settlement = next((x for x in state.merchant.settlements if x.id == settlement_id), None)
            _plan_and_execute(turn, proactive_settlement=settlement_id)
        except Exception as exc:
            log.exception("proactive event failed")
            state.status = TurnStatus.FAILED
            state.errors.append(m2_shim.mask_text(f"{type(exc).__name__}: {exc}")[:200])
        return _finish(turn)


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------
def _understand(turn: _Turn, pending: bool) -> None:
    s = turn.state
    t = time.perf_counter()
    result, llm, source = intent_agent.classify(s, pending)
    s.lang, s.intent, s.intent_confidence = result.lang, result.intent, result.confidence
    s.urgency, s.track = result.urgency, result.track
    s.status = TurnStatus.UNDERSTOOD
    turn.span("intent", f"msg ({len(s.message_masked)} chars), pending={pending}",
              f"{result.intent.value} {result.lang} urgency={result.urgency.value} conf={result.confidence:.2f} via {source}",
              t, llm=llm)


def _load_context(turn: _Turn) -> MerchantContext:
    s = turn.state
    t = time.perf_counter()
    s.merchant = context.load(s.merchant_id)
    s.status = TurnStatus.CONTEXT_LOADED
    open_issues = [f"{x.id} {x.status}" + (f" {x.cause}" if x.cause else "") for x in s.merchant.settlements
                   if x.status in ("failed", "pending")]
    turn.span("context", f"merchant {s.merchant_id}",
              "; ".join(open_issues) or "no failed/pending settlement", t)
    return s.merchant


def _fresh_flow(turn: _Turn) -> None:
    s = turn.state
    _load_context(turn)

    # low confidence / unknown -> handoff straight after UNDERSTOOD. human_request & refund never wait on confidence.
    always = (Intent.HUMAN_REQUEST, Intent.REFUND_REQUEST)
    if s.intent not in always and (s.intent == Intent.UNKNOWN or (s.intent_confidence or 0) < _policy_threshold()):
        reason = HandoffReason.UNKNOWN_INTENT if s.intent == Intent.UNKNOWN else HandoffReason.LOW_CONFIDENCE
        _hand_off(turn, reason.value)
        return
    _plan_and_execute(turn)


def _injection_flow(turn: _Turn, signals: list[str]) -> None:
    """Suspected prompt injection: nothing is planned, nothing moves, no LLM words anything. The merchant gets
    the plain ledger answer (DEMO_SCRIPT scene 4); a human gets a fraud-review brief written by code."""
    s = turn.state
    t = time.perf_counter()
    kw = intent_agent.keyword_classify(s.message_masked, pending=False)
    s.lang, s.intent, s.intent_confidence = kw.lang, kw.intent, kw.confidence
    s.urgency, s.track = kw.urgency, kw.track
    s.status = TurnStatus.UNDERSTOOD
    turn.span("intent", f"msg ({len(s.message_masked)} chars)",
              f"{s.intent.value} {s.lang} via injection guard: {', '.join(signals)}", t)
    _load_context(turn)

    # audit trail: the injected demand goes to the guardrail once (never executed) -> BLOCK NOT_IN_ALLOW_LIST row
    step = PlannedStep(step_no=gw.next_step_no(s.session_id), action_type="transfer",
                       params={"merchant_id": s.merchant_id}, reversible=False,
                       rationale="injected request from the message; audit only, never executed")
    _stamp(step, s.session_id)
    gw.advance_step_no(s.session_id, step.step_no)
    t = time.perf_counter()
    decision = m2_shim.guardrail_check(step, s)
    turn.span("guardrail", "transfer (injected, audit only)",
              f"{decision.verdict.value} {decision.reason_code.value}: {decision.reason}", t, step_no=step.step_no)
    if decision.verdict == Verdict.BLOCK:
        s.refused.append(RefusedStep(action_type=step.action_type, verdict=decision.verdict,
                                     reason_code=decision.reason_code,
                                     reason="no such action exists; nothing was planned"))
    # anything other than BLOCK is ignored on purpose: this step is never executed

    t = time.perf_counter()
    s.handoff = handoff.injection_brief(s, signals)
    s.handoff_id = handoff.save(s, s.handoff)
    s.status = TurnStatus.HANDED_OFF
    turn.span("handoff", f"reason {HandoffReason.SUSPECTED_INJECTION.value}",
              f"{s.handoff_id}: {s.handoff.decision_needed}", t)
    open_issue = any(x.status in ("failed", "pending") for x in s.merchant.settlements)
    turn.fixed_reply_key = "handoff" if open_issue else "all_good"


def _plan_and_execute(turn: _Turn, proactive_settlement: str | None = None) -> None:
    s = turn.state
    t = time.perf_counter()
    plan = plans.plan_for(s, gw.next_step_no(s.session_id), proactive_settlement)
    s.plan = [_stamp(p, s.session_id) for p in plan.steps]
    if s.plan:
        gw.advance_step_no(s.session_id, max(p.step_no for p in s.plan))
    s.status = TurnStatus.PLANNED
    turn.span("planner", f"intent {s.intent.value if s.intent else '?'}",
              " -> ".join(p.action_type for p in s.plan) or f"no steps ({plan.note or 'handoff'})", t)

    _execute(turn, list(s.plan))
    if s.status in (TurnStatus.AWAITING_CONFIRMATION, TurnStatus.HANDED_OFF, TurnStatus.FAILED):
        return
    if plan.handoff_reason:
        _hand_off(turn, plan.handoff_reason)
        return
    s.status = TurnStatus.COMPLETED


def _execute(turn: _Turn, queue: list[PlannedStep]) -> None:
    """The loop: every step goes through the guardrail; only an ALLOW reaches action.run()."""
    s = turn.state
    s.status = TurnStatus.EXECUTING
    while queue:
        step = queue.pop(0)
        t = time.perf_counter()
        decision = m2_shim.guardrail_check(step, s)
        s.decisions[step.step_no] = decision
        turn.span("guardrail", f"{step.action_type} {step.amount if step.amount is not None else ''}".strip(),
                  f"{decision.verdict.value} {decision.reason_code.value}: {decision.reason}", t, step_no=step.step_no)

        if decision.verdict == Verdict.ALLOW:
            if turn.proactive_ref and step.action_type in _proactive_consent_actions():
                # defence in depth: in a proactive session nobody asked for this money action, so it needs the
                # merchant's own yes (a resumed step is run by _resume(), never through this loop)
                raise ProactiveConsentViolation(f"{step.action_type} ALLOWed without a yes in a proactive session")
            if not _run_allowed(turn, step, decision, queue):
                return
        elif decision.verdict == Verdict.NEEDS_CONFIRMATION:
            _park_for_confirmation(turn, step, decision, queue)
            return
        else:  # BLOCK is final
            if decision.reason_code == ReasonCode.DUPLICATE_ACTION:
                earlier = action.prior_result(step.idempotency_key, step)
                if earlier:
                    s.completed.append(earlier)
                    continue
            s.refused.append(RefusedStep(action_type=step.action_type, verdict=decision.verdict,
                                         reason_code=decision.reason_code, reason=decision.reason))
            if step.action_type == ActionType.RETRIGGER_PAYOUT.value:
                # the sales steps depend on the money step having worked: drop them and ask a human
                queue.clear()
                _hand_off(turn, decision.reason_code.value)
                return


def _run_allowed(turn: _Turn, step: PlannedStep, decision: Decision, queue: list[PlannedStep],
                 kfs_shown_at: str | None = None) -> bool:
    """Execute an ALLOWed step. Returns False if the loop must stop."""
    s = turn.state
    t = time.perf_counter()
    result = action.run(step, s, decision, kfs_shown_at=kfs_shown_at)  # the ONLY call site, behind an ALLOW
    s.completed.append(result)
    turn.span("action", step.action_type,
              f"{result.status} {result.ref_id or ''}{' (replayed)' if result.replayed else ''}".strip(),
              t, status="ok" if result.status == "success" else "error", step_no=step.step_no)

    if result.status != "success":
        queue.clear()
        _hand_off(turn, HandoffReason.ACTION_FAILED.value)
        s.status = TurnStatus.FAILED  # C1.4: rollback attempted, then handoff; the brief is already written
        return False

    if step.action_type == ActionType.CHECK_ELIGIBILITY.value:
        offer = plans.followup_offer_step(s, gw.next_step_no(s.session_id))
        if offer is not None:
            _stamp(offer, s.session_id)
            gw.advance_step_no(s.session_id, offer.step_no)
            s.plan.append(offer)
            queue.append(offer)
        else:
            s.outcome_tags.append("loan_not_eligible")
    if step.action_type == ActionType.CHECK_INSURANCE.value:
        offer = plans.followup_insurance_step(s, gw.next_step_no(s.session_id))
        if offer is not None:
            _stamp(offer, s.session_id)
            gw.advance_step_no(s.session_id, offer.step_no)
            s.plan.append(offer)
            queue.append(offer)
        else:
            s.outcome_tags.append("insurance_none")
    return True


def _park_for_confirmation(turn: _Turn, step: PlannedStep, decision: Decision,
                           queue: list[PlannedStep] | None = None) -> None:
    """Guardrail said NEEDS_CONFIRMATION: store the step, stop the loop (one pending step at a time)."""
    s = turn.state
    s.pending_step, s.pending_audit_id = step, decision.audit_id
    kind = decision.confirmation_kind or "consent"
    s.pending_meta = {"kind": kind, "reason_code": decision.reason_code.value}
    if turn.proactive_ref:
        # proactive: "haan" -> fix + ticket + loan offer, so the rest of the plan resumes after the yes
        # (every remaining step still goes through the guardrail; create_offer will ask its own yes)
        s.pending_meta["proactive_ref"] = turn.proactive_ref
        if queue:
            s.pending_meta["remaining_steps"] = [p.model_dump(mode="json") for p in queue]
    if kind == "consent":
        # the KFS is presented in this turn's reply: record WHEN (RBI Digital Lending: before consent)
        s.pending_meta["kfs_shown_at"] = db.now_iso()
        s.status = TurnStatus.AWAITING_CONFIRMATION
    else:  # step_up: a human (agent desk) approves; merchant OTP is the P1 path
        s.outcome_tags.append("step_up_required")
        _hand_off(turn, decision.reason_code.value, confirmation_kind="step_up", pending_audit_id=decision.audit_id)


def _hand_off(turn: _Turn, reason_code: str, *, confirmation_kind=None, pending_audit_id=None) -> None:
    s = turn.state
    t = time.perf_counter()
    brief, llm = handoff.build(s, reason_code, confirmation_kind, pending_audit_id)
    s.handoff = brief
    s.handoff_id = handoff.save(s, brief)
    s.status = TurnStatus.HANDED_OFF
    turn.span("handoff", f"reason {reason_code}", f"{s.handoff_id}: {brief.decision_needed}", t, llm=llm)


def _resume(turn: _Turn, pending: tuple[PlannedStep, dict, int | None], *, approve: bool, actor: str,
            actor_id: str | None, kind: str | None, otp: str | None) -> None:
    """Resume (or cancel) the pending step. The guardrail runs AGAIN, with a Confirmation."""
    s = turn.state
    step, meta, audit_id = pending
    kind = kind or meta.get("kind") or "consent"
    s.plan = [step]
    turn.proactive_ref = meta.get("proactive_ref")

    if not approve:
        if kind == "consent" and step.action_type == ActionType.CREATE_OFFER.value:
            lending.record_declined_offer(step.params["merchant_id"], step.params["amount"], s.session_id,
                                          s.trace_id, meta.get("kfs_shown_at"))
            s.outcome_tags.append("offer_declined")
            s.status = TurnStatus.COMPLETED
        elif kind == "consent" and step.action_type == ActionType.OFFER_INSURANCE.value:
            insurance.record_declined(step.params["merchant_id"], step.params["product_id"], s.session_id, s.trace_id)
            s.outcome_tags.append("insurance_declined")
            s.status = TurnStatus.COMPLETED
        elif kind == "consent":  # e.g. a proactive payout: "abhi nahi" -> nothing runs, nothing is recorded as an offer
            s.outcome_tags.append("payout_declined")
            s.status = TurnStatus.COMPLETED
            if turn.proactive_ref:
                turn.notify, turn.notify_variant = True, "declined"
        else:
            _hand_off(turn, HandoffReason.MERCHANT_DECLINED_STEP_UP.value)
        return

    if kind == "step_up" and actor == "merchant" and not otp:
        # a typed "haan" can never release over-limit money: it needs OTP (button) or a human
        s.outcome_tags.append("step_up_required")
        s.pending_step, s.pending_audit_id, s.pending_meta = step, audit_id, meta
        s.status = TurnStatus.HANDED_OFF
        return

    if audit_id is None:
        raise PendingMismatch("pending step has no audit row to confirm")
    confirmation = Confirmation(pending_audit_id=audit_id, actor=actor, actor_id=actor_id, kind=kind, otp=otp)
    _refresh_eligibility(s, step)
    t = time.perf_counter()
    decision = m2_shim.guardrail_check(step, s, confirmation)
    s.decisions[step.step_no] = decision
    turn.span("guardrail", f"{step.action_type} + {actor} {kind} confirmation",
              f"{decision.verdict.value} {decision.reason_code.value}: {decision.reason}", t, step_no=step.step_no)

    if decision.verdict == Verdict.ALLOW:
        if _run_allowed(turn, step, decision, [], kfs_shown_at=meta.get("kfs_shown_at")):
            s.status = TurnStatus.COMPLETED
            if step.action_type == ActionType.CREATE_OFFER.value:
                _grant_consent(s, "loan_offer", kfs_shown=True)  # KFS was shown when the offer was parked
                turn.loan_brief = _loan_brief(s, step, decision)  # attached in _finish(), after the reply
            if step.action_type == ActionType.OFFER_INSURANCE.value:
                _grant_consent(s, "insurance_offer")
                turn.loan_brief = _insurance_brief(s, step, decision)  # same follow-up mechanism as the loan brief
            remaining = [PlannedStep.model_validate(x) for x in meta.get("remaining_steps") or []]
            if remaining:  # proactive: the yes covered THIS step only; the rest goes through the guardrail again
                s.plan.extend(remaining)
                _execute(turn, remaining)
                if s.status == TurnStatus.EXECUTING:
                    s.status = TurnStatus.COMPLETED
    elif decision.verdict == Verdict.NEEDS_CONFIRMATION:  # e.g. wrong OTP or params changed since
        _park_for_confirmation(turn, step, decision)
    else:
        s.refused.append(RefusedStep(action_type=step.action_type, verdict=decision.verdict,
                                     reason_code=decision.reason_code, reason=decision.reason))
        s.status = TurnStatus.COMPLETED


def _loan_brief(s: ConversationState, step: PlannedStep, decision: Decision) -> HandoffBrief | None:
    """Deterministic follow-up brief for the loan team (no LLM). Every value comes from the offers row and the
    guardrail decision, never from the merchant's message. Chaukas never moves loan money; the lender does."""
    done = next((a for a in s.completed if a.step_no == step.step_no and a.status == "success"), None)
    offer = lending.get_offer(done.ref_id) if done and done.ref_id else None
    if offer is None:
        return None
    kfs = offer["kfs"]
    return HandoffBrief(
        asked=m2_shim.mask_text(f"Merchant accepted a ₹{offer['amount']:,} business loan offer"),
        verified=["Key Fact Statement shown before consent",
                  f"Consent recorded (CONFIRMED_BY_MERCHANT, audit #{decision.audit_id})"],
        done=[f"Offer {offer['id']} accepted"],
        refused=[], reason_code=HandoffReason.LOAN_ACCEPTED.value, confidence=1.0,
        decision_needed=m2_shim.mask_text(
            f"Follow up with the lender on {offer['id']} and confirm next steps with the merchant"),
        suggested_step=None,
        loan=LoanFollowUp(
            offer_id=offer["id"], amount=offer["amount"], lender_name=offer["lender_name"],
            apr_pct=kfs["apr_pct"], processing_fee_inr=kfs["processing_fee_inr"],
            tenure_months=kfs["tenure_months"], total_repayable_inr=kfs["total_repayable_inr"],
            grievance_contact=kfs["grievance_contact"], kfs_shown_at=offer["kfs_shown_at"],
            consent_at=offer["consent_at"], consent_audit_id=decision.audit_id),
    )


def _insurance_brief(s: ConversationState, step: PlannedStep, decision: Decision) -> HandoffBrief | None:
    """Deterministic follow-up brief for the insurer partner (no LLM). Every value comes from the insurance_leads
    row and the guardrail decision. Chaukas issues no policy and charges no premium: the insurer follows up."""
    done = next((a for a in s.completed if a.step_no == step.step_no and a.status == "success"), None)
    lead = insurance.get_lead(done.ref_id) if done and done.ref_id else None
    if lead is None:
        return None
    return HandoffBrief(
        asked=m2_shim.mask_text(f"Merchant said yes to {lead['product_name']} (illustrative cover Rs {lead['cover_inr']:,})"),
        verified=[f"Recommended by rules: {', '.join(lead['reasons'])}",
                  f"Consent recorded (CONFIRMED_BY_MERCHANT, audit #{decision.audit_id})"],
        done=[f"Interest {lead['id']} recorded; no premium charged, no policy issued"],
        refused=[], reason_code=HandoffReason.INSURANCE_INTEREST.value, confidence=1.0,
        decision_needed=m2_shim.mask_text(
            f"Insurer partner to contact the merchant about {lead['id']} and confirm cover and premium"),
        suggested_step=None)


def _refresh_eligibility(s: ConversationState, step: PlannedStep) -> None:
    """A resume turn has no check_eligibility step, so the guardrail's offer gating (check 7) would see none."""
    if step.action_type == ActionType.CREATE_OFFER.value and s.merchant is not None:
        s.merchant.eligibility = lending.check_eligibility(step.params["merchant_id"])


def _grant_consent(s: ConversationState, purpose: str, *, kfs_shown: bool = False) -> None:
    """Append a consents row (DPDP / RBI L1). Never breaks the turn: the action already ran."""
    conn = db.connect()
    try:
        consent.grant(conn, s.merchant_id, purpose, channel=s.channel.value, session_id=s.session_id,
                      kfs_shown=kfs_shown)
    except Exception:
        log.exception("consent record failed")
    finally:
        conn.close()


def resolve_by_human(session_id: str, merchant_id: str, step: PlannedStep, pending_audit_id: int,
                     kind: str, staff_id: str) -> tuple[Decision, ActionResult | None, ConversationState]:
    """Agent-desk 'Approve & execute'. The guardrail still runs (actor=human); BLOCK stays BLOCK."""
    session = gw.load_session(session_id)
    state = _new_state(session, "[agent-desk] approve")
    state.channel, state.mode = Channel.AGENT_DESK, Mode.COPILOT
    state.merchant = context.load(merchant_id)
    state.plan = [step]
    step.session_id = session_id
    turn = _Turn(state)
    decision, result, error = None, None, None
    with create_logs.turn_scope(state.session_id, state.turn_no, state.trace_id):
        try:
            confirmation = Confirmation(pending_audit_id=pending_audit_id, actor="human", actor_id=staff_id,
                                        kind=kind)
            _refresh_eligibility(state, step)
            t = time.perf_counter()
            decision = m2_shim.guardrail_check(step, state, confirmation)
            state.decisions[step.step_no] = decision
            turn.span("guardrail", f"{step.action_type} + human approval by {staff_id}",
                      f"{decision.verdict.value} {decision.reason_code.value}: {decision.reason}", t,
                      step_no=step.step_no)
            if decision.verdict == Verdict.ALLOW:
                t = time.perf_counter()
                result = action.run(step, state, decision)
                state.completed.append(result)
                turn.span("action", step.action_type, f"{result.status} {result.ref_id or ''}".strip(), t,
                          step_no=step.step_no)
        except Exception as exc:  # still logged below; the API keeps its existing error behaviour
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            create_logs.log_human_resolve(session_id, staff_id, step.action_type, step.amount, decision, result,
                                          error=error)
    return decision, result, state


# --------------------------------------------------------------------------
# finish: reply + persistence + response
# --------------------------------------------------------------------------
def _finish(turn: _Turn) -> TurnResponse:
    s = turn.state
    if s.status == TurnStatus.FAILED and s.handoff is None:
        s.outcome_tags.append("turn_failed")
    t = time.perf_counter()
    if turn.notify:  # proactive: deterministic template, amounts from the ledger, never an LLM
        text, llm, source = notify.build(s, turn.notify_settlement, turn.notify_variant), None, "notification"
    elif turn.fixed_reply_key:  # e.g. suspected injection: no LLM reads the message or words the answer
        text, llm, source = reply_agent.template_line(s.lang, turn.fixed_reply_key), None, "template(fixed)"
    else:
        text, llm, source = reply_agent.generate(s)
    s.reply = text
    turn.span("reply", f"{s.intent.value if s.intent else '?'} in {s.lang}", f"via {source}: {len(text)} chars", t, llm=llm)

    if turn.loan_brief is not None:
        # attached only AFTER the reply: the reply (and its replay key) must not change. Status stays COMPLETED:
        # the merchant's request is done, this brief is back-office follow-up for the loan team.
        t = time.perf_counter()
        s.handoff = turn.loan_brief
        s.handoff_id = handoff.save(s, s.handoff)
        turn.span("handoff", f"reason {s.handoff.reason_code}",
                  f"{s.handoff_id}: {s.handoff.decision_needed}", t)

    if not turn.is_event:  # an event turn has no merchant message: Chaukas speaks first
        gw.record_turn(s.session_id, s.turn_no, s.trace_id, "merchant", s.message_masked, s.lang,
                       s.intent.value if s.intent else None)
    gw.record_turn(s.session_id, s.turn_no + 1, s.trace_id, "agent", text, s.lang)
    pending = (s.pending_step, s.pending_meta or {}, s.pending_audit_id) if s.pending_step else None
    gw.save_session_state(
        s.session_id, lang=s.lang, intent=s.intent.value if s.intent else None,
        urgency=s.urgency.value if s.urgency else None, track=s.track.value if s.track else None,
        pending=pending, outcome=_OUTCOME.get(s.status))

    pending_confirmation = None
    if s.pending_step is not None:
        pending_confirmation = {
            "pending_audit_id": s.pending_audit_id, "step": s.pending_step.model_dump(mode="json"),
            "kind": (s.pending_meta or {}).get("kind"), "reason_code": (s.pending_meta or {}).get("reason_code"),
            "prompt": text,
        }
        if (s.pending_meta or {}).get("kind") == "consent" and s.pending_step.action_type == ActionType.CREATE_OFFER.value:
            # structured KFS for the offer card (RBI L1: shown BEFORE Haan/Nahi); same build_kfs() as the reply
            # text and the offers.kfs_json row, so all three always match
            p = s.pending_step.params
            pending_confirmation["kfs"] = lending.build_kfs(p["merchant_id"], p["amount"]).model_dump()
        if (s.pending_meta or {}).get("kind") == "consent" and s.pending_step.action_type == ActionType.OFFER_INSURANCE.value:
            # structured insurance card (what the reply says, as data): same rules function as the guardrail
            card = insurance.recommend_for(s.pending_step.params["merchant_id"])
            if card and card["product_id"] == s.pending_step.params["product_id"]:
                pending_confirmation["insurance"] = card
    response = TurnResponse(
        session_id=s.session_id, turn_no=s.turn_no, trace_id=s.trace_id, status=s.status, lang=s.lang,
        intent=s.intent, reply=text, plan=s.plan,
        decisions=[_decision_row(next(p for p in _all_steps(s) if p.step_no == n), d) for n, d in s.decisions.items()],
        actions=s.completed, pending_confirmation=pending_confirmation, handoff=s.handoff,
        latency_ms=turn.elapsed_ms(), cost_inr=round(turn.cost, 4), spans=turn.spans,
    )
    create_logs.log_turn(response, s.message_masked, s.intent_confidence)
    return response


def _all_steps(s: ConversationState) -> list[PlannedStep]:
    steps = list(s.plan)
    if s.pending_step and all(p.step_no != s.pending_step.step_no for p in steps):
        steps.append(s.pending_step)
    return steps
