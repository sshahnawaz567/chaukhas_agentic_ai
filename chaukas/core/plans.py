"""Plan templates per intent, branching on settlement cause
(see merchant_fixtures.json _meta.cause_to_plan).

Pure functions, no I/O, no LLM. Amounts ALWAYS come from the ledger (MerchantContext.settlements),
never from the merchant's message.

Step order for a settlement: verify_ledger -> ticket (update the open one, else raise) -> retrigger.
The ticket goes BEFORE the money step so it always exists, even when the payout needs confirmation
or is blocked (the loop stops at a pending step).

Owner: Member 1 · Contract: CONTRACTS C1.1
"""
from __future__ import annotations

from dataclasses import dataclass, field

from chaukas.core.models import (
    ActionType,
    ConversationState,
    HandoffReason,
    Intent,
    MerchantContext,
    PlannedStep,
    SettlementView,
)

MAX_SETTLEMENTS_PER_TURN = 3


@dataclass
class PlanResult:
    steps: list[PlannedStep] = field(default_factory=list)
    handoff_reason: str | None = None       # set -> orchestrator hands off after running `steps`
    note: str = ""                          # why (goes to the trace / reply facts)
    unresolved: list[SettlementView] = field(default_factory=list)


class _Numberer:
    """Hands out monotonic step numbers starting at `start` (session-wide counter)."""

    def __init__(self, start: int):
        self.n = start

    def step(self, action: ActionType, params: dict, rationale: str, *, amount: int | None = None,
             reversible: bool = True) -> PlannedStep:
        s = PlannedStep(step_no=self.n, action_type=action.value, params=params, amount=amount,
                        reversible=reversible, rationale=rationale)
        self.n += 1
        return s


def _open_ticket_for(ctx: MerchantContext, settlement_id: str | None) -> dict | None:
    for t in ctx.open_tickets:
        if t.get("settlement_id") == settlement_id:
            return t
    return None


def _ticket_step(num: _Numberer, ctx: MerchantContext, settlement_id: str | None, issue: str, note: str):
    existing = _open_ticket_for(ctx, settlement_id)
    if existing:  # never a duplicate ticket for the same settlement (M002)
        return num.step(ActionType.UPDATE_TICKET,
                        {"ticket_id": existing["id"], "note": note, "status": "in_progress"},
                        f"open ticket {existing['id']} already exists for this settlement: update it")
    return num.step(ActionType.RAISE_TICKET,
                    {"merchant_id": ctx.merchant_id, "issue": issue, "settlement_id": settlement_id},
                    "no open ticket for this issue: raise one")


def _payout_step(num: _Numberer, s: SettlementView) -> PlannedStep:
    return num.step(ActionType.RETRIGGER_PAYOUT, {"settlement_id": s.id, "amount": s.amount},
                    f"{s.cause} and retriggerable; amount taken from the ledger", amount=s.amount)


def unresolved_settlements(ctx: MerchantContext) -> list[SettlementView]:
    """failed / pending settlements, newest first (retriggered and success need no action)."""
    return [s for s in ctx.settlements if s.status in ("failed", "pending")][:MAX_SETTLEMENTS_PER_TURN]


def plan_settlement_delay(state: ConversationState, start_step_no: int,
                          proactive_settlement: str | None = None) -> PlanResult:
    """`proactive_settlement` = the failed settlement the watcher found (proactive flow). Then only that
    settlement is planned, and the money step comes right after verify_ledger: nothing is written (e.g. a
    ticket saying "payout re-sent") before the merchant has said yes to the payout."""
    ctx = state.merchant
    assert ctx is not None
    num = _Numberer(start_step_no)
    res = PlanResult()
    res.unresolved = unresolved_settlements(ctx)
    if proactive_settlement is not None:
        res.unresolved = [s for s in res.unresolved if s.id == proactive_settlement]

    if not res.unresolved:
        res.note = "no failed or pending settlement"
        return res  # reply says everything is fine (scene 4 part A)

    wants_check_eligibility = True
    for s in res.unresolved:
        res.steps.append(num.step(ActionType.VERIFY_LEDGER, {"settlement_id": s.id},
                                  "read the ledger fresh before deciding"))

        if s.cause == "KYC_PENDING":
            res.steps.append(_ticket_step(num, ctx, s.id, f"Settlement {s.id} held: KYC pending",
                                          "KYC pending; merchant sent the KYC link"))
            res.handoff_reason = HandoffReason.KYC_PENDING.value
            res.note = "KYC pending: never retrigger"
            wants_check_eligibility = False
        elif s.status == "pending":  # BANK_DOWN pending: do not retrigger, give ETA
            res.steps.append(_ticket_step(num, ctx, s.id, f"Settlement {s.id} pending: bank delay",
                                          "bank delay; merchant given ETA"))
            res.note = res.note or "bank delay: waiting, no retrigger"
            wants_check_eligibility = False
        elif s.retriggerable:
            issue, note = f"Settlement {s.id} failed: {s.cause}", f"{s.cause}: payout re-sent after fix"
            if proactive_settlement is not None:  # proactive: ask for the payout before writing anything
                res.steps.append(_payout_step(num, s))
                res.steps.append(_ticket_step(num, ctx, s.id, issue, note))
            else:  # reactive: ticket first, so it exists even when the payout stops at the guardrail
                res.steps.append(_ticket_step(num, ctx, s.id, issue, note))
                res.steps.append(_payout_step(num, s))
        else:  # IFSC_MISMATCH and bank details not updated since the failure
            res.steps.append(_ticket_step(num, ctx, s.id, f"Settlement {s.id} failed: bank details not updated",
                                          "bank details not updated; merchant asked to update them"))
            res.handoff_reason = HandoffReason.BANK_DETAILS_NOT_UPDATED.value
            res.note = "IFSC_MISMATCH and bank details not updated since failure"
            wants_check_eligibility = False

    # support first, sales after: offer only when every issue was actioned without a handoff.
    if wants_check_eligibility and not res.handoff_reason:
        res.steps.append(num.step(ActionType.CHECK_ELIGIBILITY, {"merchant_id": ctx.merchant_id},
                                  "issue actioned; check loan eligibility (read-only)"))
    return res


def plan_loan_inquiry(state: ConversationState, start_step_no: int) -> PlanResult:
    ctx = state.merchant
    assert ctx is not None
    num = _Numberer(start_step_no)
    return PlanResult(steps=[num.step(ActionType.CHECK_ELIGIBILITY, {"merchant_id": ctx.merchant_id},
                                      "merchant asked about a loan")])


def plan_device_issue(state: ConversationState, start_step_no: int) -> PlanResult:
    ctx = state.merchant
    assert ctx is not None
    num = _Numberer(start_step_no)
    issue = f"Device issue ({ctx.device or 'unknown device'}): {state.message_masked[:120]}"
    return PlanResult(steps=[_ticket_step(num, ctx, None, issue, f"merchant reported again: {state.message_masked[:120]}")])


def followup_offer_step(state: ConversationState, step_no: int) -> PlannedStep | None:
    """Called after check_eligibility succeeded: build the create_offer step from the LENDER's max_amount
    (never from the merchant's words). Returns None when not eligible."""
    ctx = state.merchant
    if ctx is None or ctx.eligibility is None or not ctx.eligibility.eligible:
        return None
    amount = ctx.eligibility.max_amount
    return PlannedStep(step_no=step_no, action_type=ActionType.CREATE_OFFER.value,
                       params={"merchant_id": ctx.merchant_id, "amount": amount}, amount=amount,
                       reversible=True, rationale="eligible: offer the lender's max amount (needs consent)")


def plan_for(state: ConversationState, start_step_no: int, proactive_settlement: str | None = None) -> PlanResult:
    """Intent -> plan template. Intents that always hand off return a PlanResult with no steps."""
    intent = state.intent
    if intent == Intent.SETTLEMENT_DELAY:
        return plan_settlement_delay(state, start_step_no, proactive_settlement)
    if intent == Intent.LOAN_INQUIRY:
        return plan_loan_inquiry(state, start_step_no)
    if intent == Intent.DEVICE_ISSUE:
        return plan_device_issue(state, start_step_no)
    if intent == Intent.REFUND_REQUEST:
        return PlanResult(handoff_reason=HandoffReason.OUT_OF_SCOPE.value, note="no refund tool, by design")
    if intent == Intent.HUMAN_REQUEST:
        return PlanResult(handoff_reason=HandoffReason.HUMAN_REQUESTED.value, note="merchant asked for a human")
    return PlanResult(handoff_reason=HandoffReason.UNKNOWN_INTENT.value, note="intent not understood")
