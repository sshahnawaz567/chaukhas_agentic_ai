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
from chaukas.agents import action, context, handoff, intent as intent_agent, reply as reply_agent
from chaukas.core import m2_shim, plans
from chaukas.core.models import (
    ActionResult,
    ActionType,
    Channel,
    Confirmation,
    ConversationState,
    Decision,
    HandoffReason,
    Intent,
    MerchantContext,
    Mode,
    PlannedStep,
    ReasonCode,
    RefusedStep,
    Track,
    TurnResponse,
    TurnStatus,
    Urgency,
    Verdict,
)
from chaukas.gateway import session as gw
from chaukas.integrations import lending
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


class _Turn:
    """Per-turn bookkeeping: state, trace spans, cost."""

    def __init__(self, state: ConversationState):
        self.state = state
        self.spans: list[dict[str, Any]] = []
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
    try:
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
    try:
        _load_context(turn)
        _resume(turn, pending, approve=approve, actor=actor, actor_id=actor_id, kind=kind, otp=otp)
    except Exception as exc:
        log.exception("confirm failed")
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

    t = time.perf_counter()
    plan = plans.plan_for(s, gw.next_step_no(s.session_id))
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
            if not _run_allowed(turn, step, decision, queue):
                return
        elif decision.verdict == Verdict.NEEDS_CONFIRMATION:
            _park_for_confirmation(turn, step, decision)
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
    return True


def _park_for_confirmation(turn: _Turn, step: PlannedStep, decision: Decision) -> None:
    """Guardrail said NEEDS_CONFIRMATION: store the step, stop the loop (one pending step at a time)."""
    s = turn.state
    s.pending_step, s.pending_audit_id = step, decision.audit_id
    kind = decision.confirmation_kind or "consent"
    s.pending_meta = {"kind": kind, "reason_code": decision.reason_code.value}
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

    if not approve:
        if kind == "consent":
            lending.record_declined_offer(step.params["merchant_id"], step.params["amount"], s.session_id,
                                          s.trace_id, meta.get("kfs_shown_at"))
            s.outcome_tags.append("offer_declined")
            s.status = TurnStatus.COMPLETED
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
    t = time.perf_counter()
    decision = m2_shim.guardrail_check(step, s, confirmation)
    s.decisions[step.step_no] = decision
    turn.span("guardrail", f"{step.action_type} + {actor} {kind} confirmation",
              f"{decision.verdict.value} {decision.reason_code.value}: {decision.reason}", t, step_no=step.step_no)

    if decision.verdict == Verdict.ALLOW:
        if _run_allowed(turn, step, decision, [], kfs_shown_at=meta.get("kfs_shown_at")):
            s.status = TurnStatus.COMPLETED
    elif decision.verdict == Verdict.NEEDS_CONFIRMATION:  # e.g. wrong OTP or params changed since
        _park_for_confirmation(turn, step, decision)
    else:
        s.refused.append(RefusedStep(action_type=step.action_type, verdict=decision.verdict,
                                     reason_code=decision.reason_code, reason=decision.reason))
        s.status = TurnStatus.COMPLETED


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
    confirmation = Confirmation(pending_audit_id=pending_audit_id, actor="human", actor_id=staff_id, kind=kind)
    t = time.perf_counter()
    decision = m2_shim.guardrail_check(step, state, confirmation)
    state.decisions[step.step_no] = decision
    turn.span("guardrail", f"{step.action_type} + human approval by {staff_id}",
              f"{decision.verdict.value} {decision.reason_code.value}: {decision.reason}", t, step_no=step.step_no)
    result = None
    if decision.verdict == Verdict.ALLOW:
        t = time.perf_counter()
        result = action.run(step, state, decision)
        state.completed.append(result)
        turn.span("action", step.action_type, f"{result.status} {result.ref_id or ''}".strip(), t,
                  step_no=step.step_no)
    return decision, result, state


# --------------------------------------------------------------------------
# finish: reply + persistence + response
# --------------------------------------------------------------------------
def _finish(turn: _Turn) -> TurnResponse:
    s = turn.state
    if s.status == TurnStatus.FAILED and s.handoff is None:
        s.outcome_tags.append("turn_failed")
    t = time.perf_counter()
    text, llm, source = reply_agent.generate(s)
    s.reply = text
    turn.span("reply", f"{s.intent.value if s.intent else '?'} in {s.lang}", f"via {source}: {len(text)} chars", t, llm=llm)

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
    return TurnResponse(
        session_id=s.session_id, turn_no=s.turn_no, trace_id=s.trace_id, status=s.status, lang=s.lang,
        intent=s.intent, reply=text, plan=s.plan,
        decisions=[_decision_row(next(p for p in _all_steps(s) if p.step_no == n), d) for n, d in s.decisions.items()],
        actions=s.completed, pending_confirmation=pending_confirmation, handoff=s.handoff,
        latency_ms=turn.elapsed_ms(), cost_inr=round(turn.cost, 4), spans=turn.spans,
    )


def _all_steps(s: ConversationState) -> list[PlannedStep]:
    steps = list(s.plan)
    if s.pending_step and all(p.step_no != s.pending_step.step_no for p in steps):
        steps.append(s.pending_step)
    return steps
