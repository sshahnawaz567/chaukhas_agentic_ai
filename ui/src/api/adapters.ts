import type {
  ApiDecisionRow,
  ApiEvalDetails,
  ApiEvalMetric,
  ApiHandoffDetail,
  ApiSpan,
  ApiTurnResponse,
  BotElement,
  EvalScorecard,
  HandoffDetail,
  MetricKey,
  OfferProduct,
  RedteamCaseResult,
  SendResult,
  TicketEvent,
  TraceAgent,
  TraceRow,
  Verdict,
} from "@/lib/chaukas-types";

/**
 * Pure functions that turn real backend responses (chaukas/api/*.py) into the
 * shapes the UI components already render. No fetching here — client.ts does
 * that — so every adapter is unit-tested against recorded responses in
 * src/test/fixtures/.
 */

const AGENT: Record<ApiSpan["agent"], TraceAgent | null> = {
  gateway: null, // ingestion bookkeeping, not an agent step worth a row on stage (except the watcher, below)
  watcher: "Watcher",
  intent: "Intent",
  context: "Context",
  planner: "Plan",
  guardrail: "Guardrail",
  action: "Action",
  handoff: "Handoff",
  reply: "Reply",
};

const rupees = (amount: number) => `₹${amount.toLocaleString("en-IN")}`;
const cost = (inr: number) => `₹${inr.toFixed(3)}`;

/** "verify_ledger -> raise_ticket" reads better on stage as "verify_ledger → raise_ticket". */
const arrows = (text: string) => text.replaceAll("->", "→").replaceAll("=>", "→");

/** Guardrail span output looks like "ALLOW WITHIN_POLICY: reason" — used when no decision row matches. */
function parseGuardrail(output: string): { verdict: Verdict; reason: string } | null {
  const match = /^(ALLOW|NEEDS_CONFIRMATION|BLOCK)\s+([A-Z_]+):\s*(.*)$/.exec(output);
  if (!match) return null;
  return { verdict: match[1] as Verdict, reason: `${match[2]} · ${match[3]}` };
}

/** Spans of one turn → trace-panel rows. Guardrail rows carry the verdict in big type. */
/** The proactive trigger is emitted as a "gateway" span with input "watcher: settlement_failed:SET-…". */
const isWatcherSpan = (span: ApiSpan) =>
  span.agent === "watcher" ||
  (span.agent === "gateway" && span.input_summary.startsWith("watcher:"));

export function toTraceRows(
  spans: ApiSpan[],
  decisions: ApiDecisionRow[],
  plan: ApiTurnResponse["plan"] = [],
): TraceRow[] {
  const rows: TraceRow[] = [];
  // Spans do not carry step params: take the lending product from the plan, so a
  // credit-line check / offer reads "· product credit_line" on stage.
  const productOf = (stepNo: number | null) => {
    const product = plan.find((p) => p.step_no === stepNo)?.params["product"];
    return typeof product === "string" ? ` · product ${product}` : "";
  };
  const planProducts = [
    ...new Set(plan.map((p) => p.params["product"]).filter((x) => typeof x === "string")),
  ];
  for (const span of spans) {
    if (isWatcherSpan(span)) {
      const ref = span.input_summary.replace(/^watcher:\s*/, "").replace("settlement_failed:", "");
      rows.push({
        agent: "Watcher",
        output: `${ref} failed → Chaukas noticed it and notified the merchant · ${span.output_summary}`,
        latencyMs: span.latency_ms,
        cost: cost(span.cost_inr),
      });
      continue;
    }
    const agent = AGENT[span.agent];
    if (!agent) continue;
    const base = { agent, latencyMs: span.latency_ms, cost: cost(span.cost_inr) };

    if (span.agent === "guardrail") {
      const decision = decisions.find((d) => d.step_no === span.step_no);
      const audit = decision?.audit_id != null ? ` · audit #${decision.audit_id}` : "";
      const verdict = decision
        ? { verdict: decision.verdict, reason: `${decision.reason_code} · ${decision.reason}` }
        : parseGuardrail(span.output_summary);
      rows.push({
        ...base,
        output: `${arrows(span.input_summary)}${productOf(span.step_no)}${audit}`,
        ...(verdict ?? {}),
        // Read-only checks (no audit row) stay small so the money decisions stand out;
        // anything that is not an ALLOW (e.g. an injected "transfer" BLOCKed) is always big.
        big: Boolean(verdict && (decision?.audit_id != null || verdict.verdict !== "ALLOW")),
      });
      continue;
    }

    let output =
      span.agent === "intent" || span.agent === "context" || span.agent === "planner"
        ? span.output_summary
        : `${span.input_summary} → ${span.output_summary}`;
    if (span.agent === "action") output += productOf(span.step_no);
    if (span.agent === "planner" && planProducts.length > 0) {
      output += ` · product ${planProducts.join(", ")}`;
    }
    rows.push({ ...base, output: arrows(output) });
  }
  return rows;
}

const FAILURE: Record<string, string> = {
  IFSC_MISMATCH: "Failed: bank details (IFSC) mismatch",
  BANK_DOWN: "Failed: the bank was down",
  KYC_PENDING: "On hold: KYC pending",
};

/** The context span says e.g. "SET-99213 failed IFSC_MISMATCH". */
function settlementCause(spans: ApiSpan[], settlementId: string): string | null {
  const context = spans.find((s) => s.agent === "context");
  if (!context) return null;
  const match = new RegExp(`${settlementId}\\s+(failed|pending)\\s+([A-Z_]+)`).exec(
    context.output_summary,
  );
  if (!match) return null;
  return FAILURE[match[2] as string] ?? `${match[1]}: ${match[2]}`;
}

function settlementCard(turn: ApiTurnResponse): BotElement | null {
  const step = turn.plan.find((p) => p.action_type === "retrigger_payout");
  if (!step) return null;
  const decision = turn.decisions.find((d) => d.step_no === step.step_no);
  if (!decision) return null; // the loop stopped before the payout was even checked
  const settlementId = String(step.params["settlement_id"] ?? "");
  const amount = step.amount ?? Number(step.params["amount"] ?? 0);
  const payout = turn.actions.find((a) => a.step_no === step.step_no);
  const ticket = turn.actions.find(
    (a) =>
      (a.action_type === "raise_ticket" || a.action_type === "update_ticket") &&
      a.status === "success",
  );

  let statusPill: string;
  if (decision.verdict === "ALLOW") {
    statusPill =
      payout?.status === "success"
        ? `Re-triggered · ${payout.ref_id ?? ""}`.trim()
        : "Payout failed";
  } else if (decision.verdict === "NEEDS_CONFIRMATION") {
    statusPill = `Needs confirmation — ${decision.reason}`;
  } else {
    statusPill = `Blocked — ${decision.reason_code}`;
  }

  return {
    type: "settlement-card",
    settlement: {
      id: settlementId,
      amount: rupees(amount),
      age: "",
      failure: settlementCause(turn.spans, settlementId) ?? "Settlement did not reach the bank",
      statusPill,
      statusTone: decision.verdict,
      ...(ticket?.ref_id
        ? {
            ticket: `${ticket.ref_id} — ${
              ticket.action_type === "update_ticket" ? "updated, no duplicate" : "ticket raised"
            }`,
          }
        : {}),
      ...(decision.verdict === "ALLOW" && payout?.status === "success"
        ? { guardrailNote: `Checked by Chaukas Guardrail · ALLOW · audit #${decision.audit_id}` }
        : {}),
    },
  };
}

function loanOffer(turn: ApiTurnResponse): BotElement | null {
  const pending = turn.pending_confirmation;
  if (!pending || pending.kind !== "consent" || pending.pending_audit_id == null) return null;
  if (pending.step.action_type !== "create_offer") return null; // a payout consent is the proactive alert
  const amount = pending.step.amount ?? Number(pending.step.params["amount"] ?? 0);
  const kfs = pending.kfs;
  const product =
    pending.product ?? kfs?.product ?? (pending.step.params["product"] as OfferProduct | undefined);
  if (product === "credit_line") return creditLineOffer(pending, amount);
  return {
    type: "loan-offer",
    offer: {
      product: "term_loan",
      title: `${rupees(amount)} तक का बिज़नेस लोन ऑफ़र`,
      sub: `${kfs ? `Offered by ${kfs.lender_name}` : "Simulated lender"} via Paytm · aapki haan ke bina kuch nahi hoga`,
      pendingAuditId: String(pending.pending_audit_id),
      kfsRows: kfs
        ? [
            { label: "Loan amount", value: rupees(amount) },
            { label: "APR", value: `${kfs.apr_pct}% a year` },
            { label: "Processing fee", value: rupees(kfs.processing_fee_inr) },
            { label: "Tenure", value: `${kfs.tenure_months} months` },
            { label: "Total repayable", value: rupees(kfs.total_repayable_inr) },
            { label: "Grievance contact", value: kfs.grievance_contact },
          ]
        : [{ label: "Loan amount", value: rupees(amount) }],
      // Until the backend sends pending_confirmation.kfs (BACKEND_CHANGES_FOR_MEMBER_1.md, change 2),
      // the Key Fact Statement is only in the reply text shown just above.
      kfsNote: kfs
        ? "Mock values from the simulated lender — shown before you decide"
        : "APR, fees, tenure, total repayable and grievance contact are in the message above.",
    },
  };
}

/**
 * Short-term credit line (Postpaid-style, simulated lender). The KFS is different
 * from a term loan: free for the interest-free period, APR + late fee only after
 * the due date, and the total repayable is the amount itself when paid on time.
 */
function creditLineOffer(
  pending: NonNullable<ApiTurnResponse["pending_confirmation"]>,
  amount: number,
): BotElement {
  const kfs = pending.kfs;
  const freeDays = kfs?.interest_free_days ?? kfs?.billing_cycle_days;
  return {
    type: "loan-offer",
    offer: {
      product: "credit_line",
      title: `${rupees(amount)} तक की short-term credit line`,
      sub: `${kfs ? `Offered by ${kfs.lender_name}` : "Simulated lender"} via Paytm · aapki haan ke bina kuch nahi hoga`,
      pendingAuditId: String(pending.pending_audit_id),
      kfsRows: kfs
        ? [
            { label: "Credit limit", value: rupees(amount) },
            {
              label: "Interest-free period",
              value: freeDays ? `${freeDays} दिन तक कोई interest/fee नहीं` : "—",
            },
            { label: "After the due date", value: `${kfs.apr_pct}% a year` },
            { label: "Late fee", value: kfs.late_fee_inr != null ? rupees(kfs.late_fee_inr) : "—" },
            { label: "Processing fee", value: rupees(kfs.processing_fee_inr) },
            {
              label: "Repay on time",
              value: `${rupees(kfs.total_repayable_inr)} · ${kfs.billing_cycle_days ?? 30} din ka cycle`,
            },
            { label: "Lender", value: kfs.lender_name },
            { label: "Grievance contact", value: kfs.grievance_contact },
          ]
        : [{ label: "Credit limit", value: rupees(amount) }],
      kfsNote: kfs
        ? "Mock values from the simulated lender — shown before you decide"
        : "Interest-free period, APR, late fee and grievance contact are in the message above.",
    },
  };
}

/**
 * Proactive turn: Chaukas noticed a failed settlement and asks before re-sending it
 * (retrigger_payout parked on CONSENT_REQUIRED). Rendered as one alert with the yes/no inside.
 */
function proactiveAlert(turn: ApiTurnResponse): BotElement | null {
  const pending = turn.pending_confirmation;
  if (!turn.spans.some(isWatcherSpan)) return null;
  if (!pending || pending.pending_audit_id == null) return null;
  if (pending.step.action_type !== "retrigger_payout") return null;
  const settlementId = String(pending.step.params["settlement_id"] ?? "");
  const amount = pending.step.amount ?? Number(pending.step.params["amount"] ?? 0);
  return {
    type: "proactive-alert",
    alert: {
      pendingAuditId: String(pending.pending_audit_id),
      settlementId,
      amount: rupees(amount),
      cause: settlementCause(turn.spans, settlementId) ?? "Settlement did not reach the bank",
      text: turn.reply,
    },
  };
}

const HANDOFF_LINE: Record<string, string> = {
  LOAN_ACCEPTED: "Brief sent to the loan team",
  INSURANCE_INTEREST: "Brief sent to the insurer partner",
  SUSPECTED_INJECTION: "Flagged for fraud review — nothing was executed",
};

/**
 * Shop insurance: shown only while offer_insurance waits for the merchant's yes.
 * A BLOCK (issue unresolved, consent withdrawn, cooling-off …) or "nothing fits"
 * never reaches here, so the merchant just reads the agent's text.
 */
function insuranceOffer(turn: ApiTurnResponse): BotElement | null {
  const pending = turn.pending_confirmation;
  if (!pending || pending.kind !== "consent" || pending.pending_audit_id == null) return null;
  if (pending.step.action_type !== "offer_insurance" || !pending.insurance) return null;
  return {
    type: "insurance-offer",
    insurance: { ...pending.insurance, pendingAuditId: String(pending.pending_audit_id) },
  };
}

/** One TurnResponse → chat elements + trace rows, in the order the merchant should read them. */
export function toSendResult(turn: ApiTurnResponse): SendResult {
  const bot: BotElement[] = [];
  const alert = proactiveAlert(turn);
  if (alert) {
    bot.push(alert);
    return {
      traceId: turn.trace_id,
      bot,
      trace: toTraceRows(turn.spans, turn.decisions, turn.plan),
    };
  }
  const card = settlementCard(turn);
  if (card) bot.push(card);
  bot.push({ type: "text", text: turn.reply });
  const offer = loanOffer(turn) ?? insuranceOffer(turn);
  if (offer) bot.push(offer);
  if (turn.handoff) {
    const handoffSpan = turn.spans.find((s) => s.agent === "handoff");
    const id = handoffSpan ? /HO-[\w-]+/.exec(handoffSpan.output_summary)?.[0] : undefined;
    const who = HANDOFF_LINE[turn.handoff.reason_code] ?? "Handed to a Paytm teammate";
    bot.push({ type: "system-line", text: `${who}${id ? ` · ${id}` : ""}` });
  }
  return { traceId: turn.trace_id, bot, trace: toTraceRows(turn.spans, turn.decisions, turn.plan) };
}

/** GET /api/handoffs/{id} → the agent-desk detail and its ticket timeline. */
export function toHandoffDetail(
  raw: ApiHandoffDetail,
  merchantNameMasked: string,
): { detail: HandoffDetail; events: TicketEvent[] } {
  const detail: HandoffDetail = {
    id: raw.id,
    session_id: raw.session_id,
    merchant_id: raw.merchant_id,
    merchant_name_masked: merchantNameMasked,
    ticket_id: raw.ticket_id,
    trace_id: raw.trace_id,
    status: raw.status,
    created_at: raw.created_at,
    brief: raw.brief,
  };
  const events = raw.ticket_events.map((event, index) => ({
    ...event,
    id: index + 1,
    ticket_id: raw.ticket_id ?? "",
  }));
  return { detail, events };
}

/** Targets as numbers, in the units the scorecard tiles format (percentages as 0–1). */
const TARGETS: Record<MetricKey, number> = {
  autonomous_resolution: 0.6,
  action_accuracy: 0.99,
  unsafe_actions: 0,
  escalation_precision: 0.9,
  p95_latency_s: 4,
  cost_per_resolved_inr: 3,
};

/** eval/latest.json (+ latest_detail.json when present) → the scorecard view. */
export function toEvalScorecard(
  latest: Partial<Record<MetricKey, ApiEvalMetric>>,
  details: ApiEvalDetails | null,
): EvalScorecard {
  const metrics = {} as EvalScorecard["metrics"];
  for (const key of Object.keys(TARGETS) as MetricKey[]) {
    const m = latest[key];
    metrics[key] = m
      ? {
          value: m.unit === "%" ? m.value / 100 : m.value,
          target: TARGETS[key],
          pass: m.pass,
          detail: m.detail,
        }
      : { value: null, target: TARGETS[key], pass: null };
  }

  const redteam: RedteamCaseResult[] = (details?.redteam_results ?? []).flatMap((c) =>
    c.steps.map((step) => ({
      case_id: c.steps.length > 1 ? `${c.case_id}.${step.step}` : c.case_id,
      merchant_id: c.merchant_id,
      attack: c.steps.length > 1 ? `${c.title} (${step.action_type})` : c.title,
      expected_verdict: step.expect.verdict,
      expected_reason_code: step.expect.reason_code,
      actual_verdict: step.got.verdict,
      actual_reason_code: step.got.reason_code,
    })),
  );

  const anyMetric = Object.values(latest).find(Boolean);
  return {
    run_at: details?.extras.ran_at ?? null,
    golden_cases: details?.extras.cases ?? null,
    redteam_cases: details?.extras.redteam?.cases ?? null,
    metrics,
    redteam,
    basis: anyMetric?.basis ?? null,
  };
}
