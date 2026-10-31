export type Verdict = "ALLOW" | "NEEDS_CONFIRMATION" | "BLOCK";

export type TraceAgent =
  "Watcher" | "Intent" | "Context" | "Plan" | "Guardrail" | "Action" | "Reply" | "Handoff";

export interface Merchant {
  id: string;
  name: string;
  demoNote: string;
}

export interface SettlementCardData {
  id: string;
  amount: string;
  age: string;
  failure: string;
  note?: string;
  statusPill: string;
  statusTone: Verdict;
  ticket?: string;
  guardrailNote?: string;
}

/** Which lending product an offer is for (CONTRACTS C1 OfferProduct). */
export type OfferProduct = "term_loan" | "credit_line";

export interface LoanOfferData {
  product?: OfferProduct;
  title: string;
  sub: string;
  pendingAuditId: string;
  kfsRows: { label: string; value: string }[];
  kfsNote: string;
}

export interface BotElement {
  type:
    | "text"
    | "settlement-card"
    | "loan-offer"
    | "insurance-offer"
    | "system-line"
    | "proactive-alert";
  text?: string;
  settlement?: SettlementCardData;
  offer?: LoanOfferData;
  alert?: ProactiveAlertData;
  insurance?: InsuranceOfferData;
}

/** Shop insurance offer (simulated insurer): pending_confirmation.insurance + the audit row to confirm. */
export interface InsuranceOfferData extends ApiInsurance {
  pendingAuditId: string;
}

/** Chaukas speaks first: a failed settlement it noticed on its own, with the merchant's yes/no. */
export interface ProactiveAlertData {
  pendingAuditId: string;
  settlementId: string;
  amount: string;
  cause: string;
  text: string; // the notification wording from the backend, in the merchant's language
}

export interface ChatMessage {
  id: string;
  role: "merchant" | "bot" | "system";
  kind: BotElement["type"];
  text: string;
  settlement?: SettlementCardData;
  offer?: LoanOfferData;
  offerState?: "pending" | "consented" | "declined";
  alert?: ProactiveAlertData;
  alertState?: "pending" | "consented" | "declined";
  /** Collapsed extra text under a bubble (the DPDP notice under the AI-disclosure line). */
  details?: string;
  insurance?: InsuranceOfferData;
  insuranceState?: "pending" | "consented" | "declined";
  insuranceRef?: string; // INS-xxxxx after the merchant's yes
}

export interface TraceStep {
  id: string;
  agent: TraceAgent;
  output: string;
  verdict?: Verdict;
  reason?: string;
  big?: boolean;
  latencyMs: number;
  cost: string;
}

export type TraceRow = Omit<TraceStep, "id">;

export interface TraceTurn {
  label: string;
  rows: TraceStep[];
  streaming: boolean;
}

export interface ScriptTurn {
  merchantText: string;
  bot: BotElement[];
  trace: TraceRow[];
}

export interface ConsentScript {
  approve: { botText: string; trace: TraceRow; handoffNote?: string };
  decline: { botText: string; trace: TraceRow };
}

export interface MerchantScript {
  merchantId: string;
  traceId: string;
  maskedAccount?: string;
  quickReplies: string[];
  turns: ScriptTurn[];
  consent?: ConsentScript;
}

export interface Session {
  id: string;
  merchantId: string;
  greetingText: string;
  quickReplies: string[];
}

export interface SendResult {
  traceId: string;
  bot: BotElement[];
  trace: TraceRow[];
}

export interface ConfirmResult {
  botText: string;
  trace: TraceRow[];
  offerState: "consented" | "declined";
  /** e.g. "Brief sent to the loan team · HO-00002" when the turn created a handoff. */
  handoffNote?: string;
  /** Real API: everything the confirm turn produced (cards, reply, a second offer). Replaces botText. */
  bot?: BotElement[];
  /** offer_insurance yes: the interest record id (actions[].ref_id). */
  insuranceRef?: string;
}

/** GET|POST /api/merchants/{id}/consents (DPDP: withdrawing is as easy as granting). */
export type ConsentPurpose = "ai_assistance" | "loan_offer" | "insurance_offer";

export interface ConsentView {
  merchant_id: string;
  purposes: Record<
    ConsentPurpose,
    { state: "granted" | "withdrawn" | null; notice_version: string | null; at: string | null }
  >;
}

/** Push notification on the merchant's lock screen (proactive flow, before the chat opens). */
export interface PhoneNotice {
  title: string;
  body: string;
}

/** POST /api/events/scan for one merchant → the session Chaukas opened and its first turn. */
export interface ProactiveStart {
  session: Session;
  result: SendResult;
}

// ---------------------------------------------------------------------------
// Backend shapes (CONTRACTS.md C1 / C5) — snake_case on purpose so the real API
// response can be used as-is once the backend is connected.
// ---------------------------------------------------------------------------

export type ReasonCode =
  | "WITHIN_POLICY"
  | "CONFIRMED_BY_MERCHANT"
  | "APPROVED_BY_HUMAN"
  | "NOT_IN_ALLOW_LIST"
  | "ACTION_DISABLED"
  | "NEVER_ALLOWED"
  | "INVALID_PARAMS"
  | "LEDGER_MISMATCH"
  | "NOT_RETRIGGERABLE"
  | "DUPLICATE_ACTION"
  | "OVER_AUTO_LIMIT"
  | "OVER_DAILY_LIMIT"
  | "CONSENT_REQUIRED"
  | "OFFER_NOT_ELIGIBLE"
  | "ISSUE_UNRESOLVED"
  | "OFFER_COOLING_OFF"
  | "CONSENT_WITHDRAWN";

export interface PlannedStep {
  step_no: number;
  action_type: string;
  params: Record<string, string | number | null>;
  amount: number | null;
  reversible: boolean;
  rationale: string;
  session_id?: string | null;
}

export interface Decision {
  verdict: Verdict;
  reason_code: ReasonCode;
  reason: string;
  audit_id: number | null;
  rollback_token: string | null;
  confirmation_kind?: "consent" | "step_up" | null;
}

/** A hand-crafted malicious step for the red-team panel (demo scene 4B). UI-side preset. */
export interface RedteamAttack {
  id: string;
  title: string;
  story: string;
  merchant_id: string;
  merchant_name: string;
  check_no: number;
  step: PlannedStep;
}

export type AppView = "merchant" | "agent" | "redteam" | "audit" | "scorecard";

// --- Agent-desk (demo scene 3) ---------------------------------------------

export type HandoffStatus = "open" | "claimed" | "resolved";

/** GET /api/handoffs?status=open — one row of the queue. */
export interface HandoffSummary {
  id: string;
  merchant_id: string;
  reason_code: string; // ReasonCode or HandoffReason
  decision_needed: string;
  created_at: string;
  status: HandoffStatus;
}

export interface RefusedStep {
  action_type: string;
  verdict: Verdict;
  reason_code: ReasonCode;
  reason: string;
}

/** CONTRACTS C1 — what the human sees instead of a transcript. */
export interface HandoffBrief {
  asked: string;
  verified: string[];
  done: string[];
  refused: RefusedStep[];
  reason_code: string;
  confidence: number;
  decision_needed: string;
  suggested_step: PlannedStep | null;
  pending_audit_id?: number | null;
  confirmation_kind?: "consent" | "step_up" | null;
  /** Proposed additive (NOTES_FOR_TEAM.md B10): set on a LOAN_ACCEPTED follow-up brief. */
  loan?: LoanFollowUp | null;
}

/**
 * What the loan team needs after the merchant said haan: the accepted offer and
 * the exact Key Fact Statement the merchant saw before consenting (offers.kfs_json).
 */
export interface LoanFollowUp {
  offer_id: string;
  amount: number;
  lender_name: string;
  apr_pct: number;
  processing_fee_inr: number;
  tenure_months: number;
  total_repayable_inr: number;
  grievance_contact: string;
  kfs_shown_at: string | null;
  consent_at: string | null;
  consent_audit_id: number | null;
  // credit line (additive)
  product?: OfferProduct;
  interest_free_days?: number | null;
  late_fee_inr?: number | null;
}

/** GET /api/handoffs/{id} — the brief plus ids. */
export interface HandoffDetail {
  id: string;
  session_id: string;
  merchant_id: string;
  merchant_name_masked: string; // proposed additive field — not in C5 yet
  ticket_id: string | null;
  trace_id: string;
  status: HandoffStatus;
  created_at: string;
  brief: HandoffBrief;
}

export type TicketActor = "agent" | "human" | "merchant" | "system";

/** One `ticket_events` row (schema.sql). */
export interface TicketEvent {
  id: number;
  ticket_id: string;
  actor: TicketActor;
  actor_id: string | null;
  event_type:
    "created" | "action_taken" | "status_change" | "note" | "handoff" | "consent" | "resolved";
  detail: string;
  created_at: string;
}

export interface ActionResult {
  step_no: number;
  action_type: string;
  status: "success" | "failed" | "rolled_back";
  ref_id: string | null;
  replayed: boolean;
  error: string | null;
  audit_id: number | null;
  latency_ms: number;
}

/** POST /api/handoffs/{id}/resolve. `decision` is a proposed additive field (not in C5 yet). */
export interface ResolveResult {
  handoff: {
    id: string;
    status: HandoffStatus;
    assigned_to: string;
    human_decision: string;
    resolved_at: string;
  };
  decision?: Decision | null;
  action_result?: ActionResult | null;
}

// --- Proof (demo scene 5) -------------------------------------------------------

export type ExecutionStatus = "pending" | "success" | "failed" | "rolled_back";

/** C5: GET /api/audit — one audit_log row joined with its execution status. */
export interface AuditRow {
  id: number;
  ts: string;
  trace_id: string;
  session_id: string | null;
  merchant_id: string | null;
  actor: TicketActor;
  step_no: number | null;
  action_type: string;
  amount: number | null;
  guardrail_decision: Verdict;
  reason_code: ReasonCode;
  reason: string;
  confirms_audit_id: number | null;
  execution_status: ExecutionStatus | null; // null = never executed (no ALLOW, or red-team)
}

export type MetricKey =
  | "autonomous_resolution"
  | "action_accuracy"
  | "unsafe_actions"
  | "escalation_precision"
  | "p95_latency_s"
  | "cost_per_resolved_inr";

/** C5: GET /api/eval/latest → {metric: {value, target, pass}}. null = not run yet. */
export interface EvalMetric {
  value: number | null;
  target: number;
  pass: boolean | null;
  detail?: string; // how the number was computed (from the eval run)
}

export interface RedteamCaseResult {
  case_id: string;
  merchant_id: string;
  attack: string;
  expected_verdict: Verdict;
  expected_reason_code: ReasonCode;
  actual_verdict: Verdict | null;
  actual_reason_code: ReasonCode | null;
}

/** `run_at`, case counts and `redteam` are proposed additive fields (not in C5 yet). */
export interface EvalScorecard {
  run_at: string | null;
  golden_cases: number | null;
  redteam_cases: number | null;
  metrics: Record<MetricKey, EvalMetric>;
  basis?: string | null; // e.g. "offline run: ... cost is Rs 0" — shown so nobody over-reads the numbers
  redteam: RedteamCaseResult[];
}

// ---------------------------------------------------------------------------
// Raw backend responses (chaukas/api/*.py) that the adapters in
// src/api/adapters.ts turn into the UI shapes above.
// ---------------------------------------------------------------------------

/** GET /api/merchants */
export interface ApiMerchant {
  merchant_id: string;
  name_masked: string;
  scenario: string;
  preferred_lang: string;
}

/** POST /api/sessions */
export interface ApiSession {
  session_id: string;
  disclosure: string;
}

/** One trace span (CONTRACTS C3, chaukas/observability/trace.py). */
export interface ApiSpan {
  trace_id: string;
  session_id: string;
  turn_no: number;
  seq: number;
  agent:
    | "gateway"
    | "watcher"
    | "intent"
    | "context"
    | "planner"
    | "guardrail"
    | "action"
    | "handoff"
    | "reply";
  step_no: number | null;
  input_summary: string;
  output_summary: string;
  status: "ok" | "error";
  latency_ms: number;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_inr: number;
  ts: string;
}

export interface ApiDecisionRow {
  step_no: number;
  action_type: string;
  verdict: Verdict;
  reason_code: ReasonCode;
  reason: string;
  audit_id: number | null;
}

/** C5 TurnResponse — POST /api/sessions/{id}/messages and /confirm. */
export interface ApiTurnResponse {
  session_id: string;
  turn_no: number;
  trace_id: string;
  status: string;
  lang: string | null;
  intent: string | null;
  reply: string;
  plan: PlannedStep[];
  decisions: ApiDecisionRow[];
  actions: ActionResult[];
  pending_confirmation: {
    pending_audit_id: number | null;
    step: PlannedStep;
    kind: "consent" | "step_up" | null;
    reason_code: ReasonCode | null;
    prompt: string;
    /** The Key Fact Statement for a consent step (shown before Haan/Nahi). */
    kfs?: ApiKfs | null;
    /** offer_insurance consent: the recommended cover (simulated insurer). */
    insurance?: ApiInsurance | null;
    product?: OfferProduct;
  } | null;
  handoff: HandoffBrief | null;
  latency_ms: number;
  cost_inr: number;
  spans: ApiSpan[];
}

/** pending_confirmation.insurance (integrations/insurance.py). Figures are illustrative. */
export interface ApiInsurance {
  product_id: string;
  product_name: string;
  insurer_name: string;
  cover_inr: number;
  premium_inr: number;
  covers: string[];
  reasons: string[];
  grievance_contact: string;
  alternatives: string[];
}

/** Key Fact Statement (core/models.py KFS, lending.build_kfs). */
export interface ApiKfs {
  lender_name: string;
  apr_pct: number;
  processing_fee_inr: number;
  tenure_months: number; // credit line: one billing cycle
  total_repayable_inr: number; // credit line: the amount, if repaid within the interest-free period
  grievance_contact: string;
  // credit line (additive)
  product?: OfferProduct;
  billing_cycle_days?: number | null;
  interest_free_days?: number | null;
  late_fee_inr?: number | null;
}

/** GET /api/handoffs/{id} */
export interface ApiHandoffDetail {
  id: string;
  session_id: string;
  merchant_id: string;
  ticket_id: string | null;
  trace_id: string;
  status: HandoffStatus;
  assigned_to: string | null;
  human_decision: string | null;
  created_at: string;
  resolved_at: string | null;
  brief: HandoffBrief;
  ticket_events: Omit<TicketEvent, "id" | "ticket_id">[];
}

/** One metric in eval/latest.json (eval/run_eval.py compute_metrics). Percentages are 0–100. */
export interface ApiEvalMetric {
  label: string;
  value: number;
  unit: "%" | "count" | "s" | "INR";
  target: string;
  pass: boolean;
  detail: string;
  basis: string;
}

/** GET /api/eval/details */
export interface ApiEvalDetails {
  extras: {
    cases: number;
    ran_at: string;
    redteam: { cases: number } | null;
  };
  redteam_results: {
    case_id: string;
    attack: string;
    title: string;
    merchant_id: string;
    steps: {
      step: number;
      action_type: string;
      expect: { verdict: Verdict; reason_code: ReasonCode };
      got: { verdict: Verdict; reason_code: ReasonCode };
    }[];
  }[];
}
