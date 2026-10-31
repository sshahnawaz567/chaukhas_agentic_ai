"""ALL shared Pydantic models + enums: ConversationState, PlannedStep, Decision,
ActionResult, HandoffBrief, Confirmation, MerchantContext, Intent, ReasonCode, ...
One definition — every module imports from here.

Owner: Member 1 · Contract: CONTRACTS C1
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveInt


# --------------------------------------------------------------------------
# C1.1 Enums
# --------------------------------------------------------------------------
class Intent(str, Enum):
    SETTLEMENT_DELAY = "settlement_delay"   # support: "paisa nahi aaya" (failed OR pending settlement)
    LOAN_INQUIRY = "loan_inquiry"           # sales:   "loan milega kya?"
    DEVICE_ISSUE = "device_issue"           # support: QR/soundbox problem -> raise_ticket (non-money)
    REFUND_REQUEST = "refund_request"       # support: NO refund tool in allow-list -> always handoff
    CONFIRM = "confirm"                     # reply to a pending step: "haan bhejo" / OTP
    DENY = "deny"                           # reply to a pending step: "nahi"
    HUMAN_REQUEST = "human_request"         # "insaan se baat karao" / grievance -> ALWAYS handoff
    UNKNOWN = "unknown"                     # low confidence / anything else -> handoff


class Track(str, Enum):
    SUPPORT = "support"
    SALES = "sales"


class Urgency(str, Enum):
    LOW = "low"
    MED = "med"
    HIGH = "high"


class Mode(str, Enum):
    AUTONOMOUS = "autonomous"
    COPILOT = "copilot"


class Channel(str, Enum):
    CHAT = "chat"
    VOICE = "voice"
    AGENT_DESK = "agent_desk"


class ActionType(str, Enum):  # == policy.yaml allow_list (+ never_allowed for red-team)
    VERIFY_LEDGER = "verify_ledger"          # read-only
    CHECK_ELIGIBILITY = "check_eligibility"  # read-only
    RETRIGGER_PAYOUT = "retrigger_payout"    # money
    RAISE_TICKET = "raise_ticket"
    UPDATE_TICKET = "update_ticket"
    CREATE_OFFER = "create_offer"            # sales, always needs consent


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class ReasonCode(str, Enum):  # MUST equal schema.sql audit_log.reason_code CHECK list
    WITHIN_POLICY = "WITHIN_POLICY"
    CONFIRMED_BY_MERCHANT = "CONFIRMED_BY_MERCHANT"
    APPROVED_BY_HUMAN = "APPROVED_BY_HUMAN"
    NOT_IN_ALLOW_LIST = "NOT_IN_ALLOW_LIST"
    ACTION_DISABLED = "ACTION_DISABLED"  # kill switch (policy.yaml disabled_actions)
    NEVER_ALLOWED = "NEVER_ALLOWED"
    INVALID_PARAMS = "INVALID_PARAMS"
    LEDGER_MISMATCH = "LEDGER_MISMATCH"
    NOT_RETRIGGERABLE = "NOT_RETRIGGERABLE"
    DUPLICATE_ACTION = "DUPLICATE_ACTION"
    OVER_AUTO_LIMIT = "OVER_AUTO_LIMIT"
    OVER_DAILY_LIMIT = "OVER_DAILY_LIMIT"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    OFFER_NOT_ELIGIBLE = "OFFER_NOT_ELIGIBLE"
    ISSUE_UNRESOLVED = "ISSUE_UNRESOLVED"
    OFFER_COOLING_OFF = "OFFER_COOLING_OFF"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"  # BLOCK: merchant withdrew loan_offer consent (DPDP s.6), schema v3.2


class HandoffReason(str, Enum):  # handoffs.reason_code = a ReasonCode OR one of these
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNKNOWN_INTENT = "UNKNOWN_INTENT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # e.g. refund_request
    BANK_DETAILS_NOT_UPDATED = "BANK_DETAILS_NOT_UPDATED"  # IFSC_MISMATCH, not fixed yet
    KYC_PENDING = "KYC_PENDING"
    ACTION_FAILED = "ACTION_FAILED"
    MERCHANT_DECLINED_STEP_UP = "MERCHANT_DECLINED_STEP_UP"
    HUMAN_REQUESTED = "HUMAN_REQUESTED"  # merchant asked for a human
    LOAN_ACCEPTED = "LOAN_ACCEPTED"  # ADDITIVE: merchant accepted an offer -> back-office follow-up, not an approval
    SUSPECTED_INJECTION = "SUSPECTED_INJECTION"  # ADDITIVE: message carries instructions aimed at the AI -> fraud review


class TurnStatus(str, Enum):  # the state machine — see C1.4
    RECEIVED = "received"
    UNDERSTOOD = "understood"
    CONTEXT_LOADED = "context_loaded"
    PLANNED = "planned"
    EXECUTING = "executing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    HANDED_OFF = "handed_off"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------
# C1.2 Per-action params (validated BEFORE the guardrail sees them)
# --------------------------------------------------------------------------
class VerifyLedgerParams(BaseModel):
    settlement_id: str


class RetriggerPayoutParams(BaseModel):
    # payout account is NOT a param: Action Agent resolves it from merchant_id via detokenise()
    settlement_id: str
    amount: PositiveInt


class RaiseTicketParams(BaseModel):
    merchant_id: str
    issue: str
    settlement_id: str | None = None


class UpdateTicketParams(BaseModel):
    ticket_id: str
    note: str
    status: Literal["open", "in_progress", "resolved"] | None = None


# ADDITIVE (credit line): which lending product a check / offer is for. Default = the original term loan,
# so every step written before this field existed validates and audits exactly as before.
OfferProduct = Literal["term_loan", "credit_line"]


class CheckEligibilityParams(BaseModel):
    merchant_id: str
    product: OfferProduct = "term_loan"  # ADDITIVE


class CreateOfferParams(BaseModel):
    merchant_id: str
    amount: PositiveInt
    product: OfferProduct = "term_loan"  # ADDITIVE: the guardrail caps the amount by THIS product's lender answer


PARAMS_BY_ACTION: dict[ActionType, type[BaseModel]] = {
    ActionType.VERIFY_LEDGER: VerifyLedgerParams,
    ActionType.CHECK_ELIGIBILITY: CheckEligibilityParams,
    ActionType.RETRIGGER_PAYOUT: RetriggerPayoutParams,
    ActionType.RAISE_TICKET: RaiseTicketParams,
    ActionType.UPDATE_TICKET: UpdateTicketParams,
    ActionType.CREATE_OFFER: CreateOfferParams,
}


# --------------------------------------------------------------------------
# C1.3 Core models
# --------------------------------------------------------------------------
class PlannedStep(BaseModel):
    step_no: int  # MONOTONIC PER SESSION (not per turn) -> idempotency key stays unique across turns
    action_type: str  # str, not ActionType: the guardrail must be able to SEE and BLOCK unknown actions
    params: dict
    amount: int | None = None  # copy of params.amount for money actions
    reversible: bool = True
    rationale: str  # why the planner chose this step (goes to brief / trace)
    # ADDITIVE (not in C1 text): the orchestrator stamps the session so the key is self-contained
    # and a step serialised into sessions.pending_step_json / a handoff brief can be resumed later.
    session_id: str | None = None

    @property
    def idempotency_key(self) -> str:
        """f"{session_id}:{step_no}" — session_id is stamped by the orchestrator."""
        if not self.session_id:
            raise ValueError("PlannedStep.session_id not set; orchestrator must stamp it")
        return f"{self.session_id}:{self.step_no}"


class Confirmation(BaseModel):  # passed to guardrail when resuming a NEEDS_CONFIRMATION step
    pending_audit_id: int  # the NEEDS_CONFIRMATION audit row being resolved
    actor: Literal["merchant", "human"]
    actor_id: str | None = None  # staff id for human
    kind: Literal["consent", "step_up"]
    otp: str | None = None  # step_up only (mock OTP in prototype)


class Decision(BaseModel):
    verdict: Verdict
    reason_code: ReasonCode
    reason: str  # human-readable, built from reason_code + numbers
    audit_id: int | None  # None only for read-only steps (not audited)
    rollback_token: str | None  # set only when verdict == ALLOW and action is a write
    confirmation_kind: Literal["consent", "step_up"] | None = None  # set when NEEDS_CONFIRMATION


class ActionResult(BaseModel):
    step_no: int
    action_type: str
    status: Literal["success", "failed", "rolled_back"]
    ref_id: str | None = None  # payout_ref / ticket_id / offer_id
    replayed: bool = False  # True = idempotent replay of an earlier execution
    error: str | None = None  # masked
    audit_id: int | None = None
    latency_ms: int


class RefusedStep(BaseModel):
    action_type: str
    verdict: Verdict
    reason_code: ReasonCode
    reason: str


class LoanFollowUp(BaseModel):  # ADDITIVE: what the loan team needs; values from the offers row, never the LLM
    offer_id: str
    amount: int
    lender_name: str
    apr_pct: float
    processing_fee_inr: int
    tenure_months: int
    total_repayable_inr: int
    grievance_contact: str
    kfs_shown_at: str | None
    consent_at: str | None
    consent_audit_id: int | None  # the ALLOW CONFIRMED_BY_MERCHANT audit row
    # ADDITIVE (credit line)
    product: OfferProduct = "term_loan"
    interest_free_days: int | None = None
    late_fee_inr: int | None = None


class HandoffBrief(BaseModel):  # agent-desk renders THIS; never a transcript
    asked: str  # what the merchant wanted, 1 line, masked
    verified: list[str]  # facts checked fresh, e.g. "SET-51002 failed, IFSC_MISMATCH"
    done: list[str]  # actions already executed
    refused: list[RefusedStep]  # what Chaukas would NOT do, and why
    reason_code: str  # ReasonCode or HandoffReason
    confidence: float  # 0..1
    decision_needed: str  # the ONE decision the human must make
    suggested_step: PlannedStep | None = None  # copilot "one-click execute" (still goes through guardrail)
    # ADDITIVE: what the desk needs to resume the step through the guardrail (Confirmation).
    pending_audit_id: int | None = None
    confirmation_kind: Literal["consent", "step_up"] | None = None
    loan: LoanFollowUp | None = None  # ADDITIVE: set only on a LOAN_ACCEPTED brief


class SettlementView(BaseModel):
    id: str
    amount: int
    settlement_date: str
    status: Literal["success", "failed", "pending", "retriggered"]
    cause: Literal["IFSC_MISMATCH", "BANK_DOWN", "KYC_PENDING"] | None
    retriggerable: bool  # computed: failed AND (BANK_DOWN OR IFSC fixed after failure)


class LenderDecision(BaseModel):  # output of the SIMULATED lender
    eligible: bool
    max_amount: int
    reason_codes: list[str]
    product: OfferProduct = "term_loan"  # ADDITIVE


class MerchantContext(BaseModel):  # what Context Agent puts in state — tokens, not raw PII
    merchant_id: str
    name_masked: str  # "Sh****"
    account_ref: str  # token, detokenised only by Action Agent
    preferred_lang: str
    kyc_status: str
    device: str | None
    gmv_30d: int
    bank_details_updated_at: str | None
    settlements: list[SettlementView]  # FRESH from DB every turn, never cached
    open_tickets: list[dict]  # {id, settlement_id, issue, status}
    has_open_handoff: bool
    declined_offer_recently: bool  # within offer_cooling_off_days
    eligibility: LenderDecision | None = None  # filled by check_eligibility step
    credit_line: LenderDecision | None = None  # ADDITIVE: filled by check_eligibility(product=credit_line)


class TurnRecord(BaseModel):  # history entry (mirrors `turns` table)
    turn_no: int
    role: Literal["merchant", "agent", "human"]
    text_masked: str
    lang: str | None = None


# --------------------------------------------------------------------------
# C1.4 ConversationState
# --------------------------------------------------------------------------
class ConversationState(BaseModel):
    # identity
    session_id: str
    turn_no: int
    trace_id: str  # new per turn
    merchant_id: str
    channel: Channel
    mode: Mode
    # input (masked at ingestion — raw text never stored in state)
    message_masked: str
    history: list[TurnRecord] = Field(default_factory=list)  # last N turns, masked
    # understand
    lang: str | None = None
    intent: Intent | None = None
    intent_confidence: float | None = None
    urgency: Urgency | None = None
    track: Track | None = None
    # context
    merchant: MerchantContext | None = None
    # decide / act
    plan: list[PlannedStep] = Field(default_factory=list)
    decisions: dict[int, Decision] = Field(default_factory=dict)  # step_no -> guardrail decision
    completed: list[ActionResult] = Field(default_factory=list)
    pending_step: PlannedStep | None = None  # persisted to sessions.pending_step_json
    pending_audit_id: int | None = None
    # escalate / reply
    handoff: HandoffBrief | None = None
    reply: str | None = None
    status: TurnStatus = TurnStatus.RECEIVED
    errors: list[str] = Field(default_factory=list)  # masked
    # ADDITIVE (orchestrator bookkeeping, all optional):
    refused: list[RefusedStep] = Field(default_factory=list)
    pending_meta: dict | None = None  # extras saved with pending_step, e.g. kfs_shown_at
    handoff_id: str | None = None
    outcome_tags: list[str] = Field(default_factory=list)  # e.g. offer_declined, nothing_pending, step_up_required


# --------------------------------------------------------------------------
# C3 integration return types (shared with eval / trace view)
# --------------------------------------------------------------------------
class LedgerStatus(BaseModel):
    found: bool
    status: str | None = None
    amount: int | None = None
    cause: str | None = None
    retry_count: int = 0


class PayoutResult(BaseModel):
    status: Literal["success", "failed"]
    payout_ref: str | None = None
    error: str | None = None


class Ticket(BaseModel):
    ticket_id: str
    status: str


class KFS(BaseModel):  # Key Fact Statement — MOCK values from config/lender_sim.yaml
    lender_name: str
    apr_pct: float
    processing_fee_inr: int
    tenure_months: int
    total_repayable_inr: int
    grievance_contact: str
    # ADDITIVE (credit line). For a credit line: tenure_months = one billing cycle, total_repayable_inr = the
    # amount if repaid within the interest-free period; APR and late fee apply after the due date.
    product: OfferProduct = "term_loan"
    billing_cycle_days: int | None = None
    interest_free_days: int | None = None
    late_fee_inr: int | None = None


class Offer(BaseModel):
    offer_id: str
    status: str


class RollbackResult(BaseModel):
    ok: bool
    detail: str


# --------------------------------------------------------------------------
# C5 TurnResponse
# --------------------------------------------------------------------------
class TurnResponse(BaseModel):
    session_id: str
    turn_no: int
    trace_id: str
    status: TurnStatus
    lang: str | None = None
    intent: Intent | None = None
    reply: str  # in merchant's language
    plan: list[PlannedStep] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)  # [{step_no, action_type, verdict, reason_code, reason, audit_id}]
    actions: list[ActionResult] = Field(default_factory=list)
    pending_confirmation: dict | None = None  # {pending_audit_id, step, kind, reason_code, prompt}
    handoff: HandoffBrief | None = None
    latency_ms: int = 0
    cost_inr: float = 0.0
    # ADDITIVE: spans of this turn, so the UI trace panel works even before ops.py (Member 2) lands
    spans: list[dict[str, Any]] = Field(default_factory=list)
