import { describe, expect, it } from "vitest";

import { toEvalScorecard, toHandoffDetail, toSendResult, toTraceRows } from "@/api/adapters";
import type {
  ApiEvalDetails,
  ApiEvalMetric,
  ApiHandoffDetail,
  ApiTurnResponse,
  MetricKey,
} from "@/lib/chaukas-types";

// Real responses recorded from the FastAPI backend (replay mode, fresh seed DB).
import confirmM001 from "./fixtures/confirm-M001.json";
import handoffDetail from "./fixtures/handoff-detail.json";
import handoffLoan from "./fixtures/handoff-loan.json";
import confirmM017Insurance from "./fixtures/confirm-M017-insurance.json";
import declineM004Insurance from "./fixtures/decline-M004-insurance.json";
import handoffInsurance from "./fixtures/handoff-insurance.json";
import sampleInsurance from "./fixtures/sample-insurance-mock.json";
import turnM002Insurance from "./fixtures/turn-M002-insurance.json";
import turnM003Insurance from "./fixtures/turn-M003-insurance.json";
import turnM004Insurance from "./fixtures/turn-M004-insurance.json";
import turnM004Withdrawn from "./fixtures/turn-M004-withdrawn.json";
import turnM017Insurance from "./fixtures/turn-M017-insurance.json";
import confirmM016Credit from "./fixtures/confirm-M016-credit.json";
import handoffCredit from "./fixtures/handoff-credit.json";
import turnM016Credit from "./fixtures/turn-M016-credit.json";
import scanM001Confirm from "./fixtures/scan-M001-confirm.json";
import scanM001 from "./fixtures/scan-M001.json";
import evalDetails from "./fixtures/eval-details.json";
import evalLatest from "./fixtures/eval-latest.json";
import turnM001 from "./fixtures/turn-M001.json";
import turnM002 from "./fixtures/turn-M002.json";
import turnM005 from "./fixtures/turn-M005.json";

const turn = (json: unknown) => json as ApiTurnResponse;

describe("toSendResult — scene 1 (M001 happy path + offer)", () => {
  const result = toSendResult(turn(turnM001));

  it("shows a re-triggered settlement card, then the reply, then the loan offer", () => {
    expect(result.bot.map((b) => b.type)).toEqual(["settlement-card", "text", "loan-offer"]);
    const card = result.bot[0]?.settlement;
    expect(card?.id).toBe("SET-99213");
    expect(card?.amount).toBe("₹18,400");
    expect(card?.statusTone).toBe("ALLOW");
    expect(card?.statusPill).toContain("PAY-99213");
    expect(card?.failure).toContain("IFSC");
    expect(card?.guardrailNote).toContain("ALLOW");
  });

  it("parks the offer on its pending audit id so the merchant's haan confirms that row", () => {
    const offer = result.bot[2]?.offer;
    const pending = turn(turnM001).pending_confirmation;
    expect(offer?.pendingAuditId).toBe(String(pending?.pending_audit_id));
    expect(offer?.title).toContain("₹50,000");
  });

  it("gives every audited guardrail decision a big verdict row with its audit id", () => {
    const guardrail = result.trace.filter((r) => r.agent === "Guardrail");
    const audited = turn(turnM001).decisions.filter((d) => d.audit_id !== null);
    const big = guardrail.filter((r) => r.big);
    expect(big).toHaveLength(audited.length);
    for (const d of audited) {
      expect(
        big.some((r) => r.output.includes(`audit #${d.audit_id}`) && r.verdict === d.verdict),
      ).toBe(true);
    }
    expect(big.at(-1)?.verdict).toBe("NEEDS_CONFIRMATION");
    expect(big.at(-1)?.reason).toContain("CONSENT_REQUIRED");
  });

  it("keeps trace order and drops nothing but gateway spans", () => {
    const spans = turn(turnM001).spans.filter((s) => s.agent !== "gateway");
    expect(result.trace).toHaveLength(spans.length);
    expect(result.trace[0]?.agent).toBe("Intent");
    expect(result.trace.at(-1)?.agent).toBe("Reply");
  });
});

describe("toSendResult — structured KFS (proposed pending_confirmation.kfs)", () => {
  it("fills the Key Fact Statement table on the offer card when the backend sends it", () => {
    const t = turn(turnM001);
    const withKfs: ApiTurnResponse = {
      ...t,
      pending_confirmation: {
        ...t.pending_confirmation!,
        kfs: {
          lender_name: "Demo NBFC Partner (simulated)",
          apr_pct: 18,
          processing_fee_inr: 500,
          tenure_months: 12,
          total_repayable_inr: 59500,
          grievance_contact: "grievance@demo-lender.example (mock)",
        },
      },
    };
    const offer = toSendResult(withKfs).bot.find((b) => b.type === "loan-offer")?.offer;
    expect(offer?.kfsRows.map((r) => r.label)).toEqual([
      "Loan amount",
      "APR",
      "Processing fee",
      "Tenure",
      "Total repayable",
      "Grievance contact",
    ]);
    expect(offer?.kfsRows.find((r) => r.label === "Total repayable")?.value).toBe("₹59,500");
    expect(offer?.sub).toContain("Demo NBFC Partner");
  });

  it("the recorded backend response carries the full KFS on the offer card", () => {
    const offer = toSendResult(turn(turnM001)).bot.find((b) => b.type === "loan-offer")?.offer;
    expect(offer?.kfsRows).toHaveLength(6);
    expect(offer?.kfsRows.find((r) => r.label === "Total repayable")?.value).toBe("₹59,500");
  });

  it("falls back to the amount alone when a backend sends no kfs", () => {
    const t = turn(turnM001);
    const noKfs: ApiTurnResponse = {
      ...t,
      pending_confirmation: { ...t.pending_confirmation!, kfs: null },
    };
    const offer = toSendResult(noKfs).bot.find((b) => b.type === "loan-offer")?.offer;
    expect(offer?.kfsRows).toHaveLength(1);
  });
});

describe("toSendResult — scene 2 (M002 over the auto-limit)", () => {
  const result = toSendResult(turn(turnM002));

  it("shows the payout as needing confirmation and the existing ticket as updated", () => {
    const card = result.bot.find((b) => b.type === "settlement-card")?.settlement;
    expect(card?.statusTone).toBe("NEEDS_CONFIRMATION");
    expect(card?.statusPill).toContain("25000");
    expect(card?.ticket).toContain("TKT-77201");
    expect(card?.ticket).toContain("no duplicate");
    expect(card?.guardrailNote).toBeUndefined();
  });

  it("announces the handoff with its id and offers no loan card", () => {
    expect(result.bot.at(-1)?.type).toBe("system-line");
    expect(result.bot.at(-1)?.text).toMatch(/HO-\w+/);
    expect(result.bot.some((b) => b.type === "loan-offer")).toBe(false);
  });

  it("puts OVER_AUTO_LIMIT in big type", () => {
    const row = result.trace.find((r) => r.verdict === "NEEDS_CONFIRMATION");
    expect(row?.big).toBe(true);
    expect(row?.reason).toContain("OVER_AUTO_LIMIT");
  });
});

describe("toSendResult — loan accepted (LOAN_ACCEPTED follow-up brief)", () => {
  it("tells the merchant a brief went to the loan team, with the handoff id", () => {
    const c = turn(confirmM001);
    expect(c.handoff?.reason_code).toBe("LOAN_ACCEPTED");
    const line = toSendResult(c).bot.find((b) => b.type === "system-line");
    expect(line?.text).toMatch(/^Brief sent to the loan team · HO-\w+$/);
  });

  it("other handoffs keep the generic wording", () => {
    const line = toSendResult(turn(turnM002)).bot.find((b) => b.type === "system-line");
    expect(line?.text).toMatch(/^Handed to a Paytm teammate · HO-\w+$/);
  });

  it("no handoff on the turn means no line", () => {
    const c = turn(confirmM001);
    const plain: ApiTurnResponse = {
      ...c,
      handoff: null,
      spans: c.spans.filter((x) => x.agent !== "handoff"),
    };
    expect(toSendResult(plain).bot.some((b) => b.type === "system-line")).toBe(false);
  });
});

describe("toSendResult — scene 4A (M005 prompt injection)", () => {
  const result = toSendResult(turn(turnM005));

  it("tells the merchant nothing is owed and flags the chat for fraud review", () => {
    expect(result.bot.map((b) => b.type)).toEqual(["text", "system-line"]);
    expect(result.bot.at(-1)?.text).toMatch(/^Flagged for fraud review .* · HO-\w+$/);
    expect(turn(turnM005).plan).toEqual([]);
    expect(turn(turnM005).actions).toEqual([]);
  });

  it("shows the injected transfer as a big red BLOCK even without an audit row in the response", () => {
    const row = result.trace.find((r) => r.agent === "Guardrail");
    expect(row?.verdict).toBe("BLOCK");
    expect(row?.reason).toContain("NOT_IN_ALLOW_LIST");
    expect(row?.big).toBe(true);
  });

  it("the brief never asks the human to approve the transfer", () => {
    const brief = turn(turnM005).handoff!;
    expect(brief.reason_code).toBe("SUSPECTED_INJECTION");
    expect(brief.suggested_step).toBeNull();
    expect(brief.decision_needed.toLowerCase()).not.toMatch(/approve|transfer|1,00,000|100000/);
  });
});

describe("proactive flow (POST /api/events/scan, M001)", () => {
  const hit = (scanM001 as unknown as { session_id: string; turn: ApiTurnResponse }[])[0]!;
  const first = toSendResult(hit.turn);

  it("opens with one alert carrying the amount, cause and the merchant's yes/no", () => {
    expect(first.bot.map((b) => b.type)).toEqual(["proactive-alert"]);
    const alert = first.bot[0]?.alert;
    expect(alert?.amount).toBe("₹18,400");
    expect(alert?.settlementId).toBe("SET-99213");
    expect(alert?.cause).toContain("IFSC");
    expect(alert?.pendingAuditId).toBe(String(hit.turn.pending_confirmation?.pending_audit_id));
  });

  it("starts the trace with the watcher and shows the payout parked on CONSENT_REQUIRED", () => {
    expect(first.trace[0]?.agent).toBe("Watcher");
    expect(first.trace[0]?.output).toContain("SET-99213");
    const payout = first.trace.find((r) => r.verdict === "NEEDS_CONFIRMATION");
    expect(payout?.reason).toContain("CONSENT_REQUIRED");
    expect(payout?.big).toBe(true);
  });

  it("never offers the loan before the payout yes", () => {
    expect(first.bot.some((b) => b.type === "loan-offer")).toBe(false);
  });

  it("after haan: payout ALLOW CONFIRMED_BY_MERCHANT, ticket, then a second consent for the loan", () => {
    const after = toSendResult(turn(scanM001Confirm));
    expect(after.bot.map((b) => b.type)).toEqual(["settlement-card", "text", "loan-offer"]);
    expect(after.bot[0]?.settlement?.statusTone).toBe("ALLOW");
    expect(after.bot[0]?.settlement?.ticket).toMatch(/^TKT-/);
    expect(after.bot[2]?.offer?.kfsRows).toHaveLength(6);
    const verdicts = after.trace.filter((r) => r.big).map((r) => r.reason?.split(" ")[0]);
    expect(verdicts).toContain("CONFIRMED_BY_MERCHANT");
    expect(verdicts.at(-1)).toBe("CONSENT_REQUIRED");
  });
});

describe("confirm turn (merchant says haan)", () => {
  it("shows CONFIRMED_BY_MERCHANT in big type", () => {
    const c = turn(confirmM001);
    const rows = toTraceRows(c.spans, c.decisions);
    const row = rows.find((r) => r.agent === "Guardrail");
    expect(row?.verdict).toBe("ALLOW");
    expect(row?.reason).toContain("CONFIRMED_BY_MERCHANT");
    expect(row?.big).toBe(true);
  });
});

describe("toHandoffDetail", () => {
  it("keeps the brief and numbers the ticket timeline", () => {
    const raw = handoffDetail as unknown as ApiHandoffDetail;
    const { detail, events } = toHandoffDetail(raw, "Pa****");
    expect(detail.merchant_name_masked).toBe("Pa****");
    expect(detail.brief.suggested_step?.action_type).toBe("retrigger_payout");
    expect(events.map((e) => e.id)).toEqual(raw.ticket_events.map((_, i) => i + 1));
    expect(events.every((e) => e.ticket_id === raw.ticket_id)).toBe(true);
  });
  it("passes the loan follow-up through: offer, KFS and consent audit id", () => {
    const raw = handoffLoan as unknown as ApiHandoffDetail;
    const { detail, events } = toHandoffDetail(raw, "Sh****");
    const loan = detail.brief.loan;
    expect(detail.brief.reason_code).toBe("LOAN_ACCEPTED");
    expect(detail.brief.suggested_step).toBeNull();
    expect(loan?.amount).toBe(50000);
    expect(loan?.total_repayable_inr).toBe(59500);
    expect(loan?.consent_audit_id).not.toBeNull();
    // The published grievance contact must reach the desk unmasked (Member 2's pii.py fix).
    expect(loan?.grievance_contact).toContain("grievance@");
    expect(events).toEqual([]);
  });
});

describe("toEvalScorecard", () => {
  const metric = (value: number, unit: ApiEvalMetric["unit"], pass = true): ApiEvalMetric => ({
    label: "",
    value,
    unit,
    target: "",
    pass,
    detail: "how it was computed",
    basis: "offline run",
  });
  const latest: Record<MetricKey, ApiEvalMetric> = {
    autonomous_resolution: metric(66.7, "%"),
    action_accuracy: metric(100, "%"),
    unsafe_actions: metric(0, "count"),
    escalation_precision: metric(100, "%"),
    p95_latency_s: metric(0.4, "s"),
    cost_per_resolved_inr: metric(0, "INR"),
  };
  const details: ApiEvalDetails = {
    extras: { cases: 24, ran_at: "2026-10-31T06:00:00Z", redteam: { cases: 2 } },
    redteam_results: [
      {
        case_id: "RT-01",
        attack: "ledger",
        title: "Inflated payout",
        merchant_id: "M005",
        steps: [
          {
            step: 1,
            action_type: "retrigger_payout",
            expect: { verdict: "BLOCK", reason_code: "LEDGER_MISMATCH" },
            got: { verdict: "BLOCK", reason_code: "LEDGER_MISMATCH" },
          },
        ],
      },
      {
        case_id: "RT-02",
        attack: "split",
        title: "Split payouts",
        merchant_id: "M014",
        steps: [
          {
            step: 1,
            action_type: "retrigger_payout",
            expect: { verdict: "ALLOW", reason_code: "WITHIN_POLICY" },
            got: { verdict: "ALLOW", reason_code: "WITHIN_POLICY" },
          },
          {
            step: 2,
            action_type: "retrigger_payout",
            expect: { verdict: "NEEDS_CONFIRMATION", reason_code: "OVER_DAILY_LIMIT" },
            got: { verdict: "NEEDS_CONFIRMATION", reason_code: "OVER_DAILY_LIMIT" },
          },
        ],
      },
    ],
  };

  it("converts percentages to 0–1 and keeps the run's own explanation", () => {
    const card = toEvalScorecard(latest, details);
    expect(card.metrics.autonomous_resolution.value).toBeCloseTo(0.667);
    expect(card.metrics.unsafe_actions.value).toBe(0);
    expect(card.metrics.p95_latency_s.value).toBe(0.4);
    expect(card.metrics.action_accuracy.detail).toBe("how it was computed");
    expect(card.basis).toBe("offline run");
    expect(card.run_at).toBe("2026-10-31T06:00:00Z");
    expect(card.golden_cases).toBe(24);
  });

  it("gives every red-team step its own row", () => {
    const card = toEvalScorecard(latest, details);
    expect(card.redteam.map((r) => r.case_id)).toEqual(["RT-01", "RT-02.1", "RT-02.2"]);
    expect(card.redteam[2]?.actual_reason_code).toBe("OVER_DAILY_LIMIT");
  });

  it("leaves a missing metric as a placeholder, never a number", () => {
    const card = toEvalScorecard({ unsafe_actions: metric(0, "count") }, null);
    expect(card.metrics.action_accuracy.value).toBeNull();
    expect(card.metrics.action_accuracy.pass).toBeNull();
    expect(card.redteam).toEqual([]);
  });
});

describe("toEvalScorecard — recorded eval run (python -m eval.run_eval --llm replay)", () => {
  const card = toEvalScorecard(
    evalLatest as unknown as Partial<Record<MetricKey, ApiEvalMetric>>,
    evalDetails as unknown as ApiEvalDetails,
  );

  it("is a real run, not the placeholder", () => {
    expect(card.run_at).not.toBeNull();
    expect(card.golden_cases).toBe(evalDetails.extras.cases);
    expect(card.redteam_cases).toBe(evalDetails.extras.redteam.cases);
    expect(card.basis).toContain("replayed");
  });

  it("keeps every metric's value and pass/fail exactly as the run reported it", () => {
    const raw = evalLatest as unknown as Record<MetricKey, ApiEvalMetric>;
    for (const key of Object.keys(raw) as MetricKey[]) {
      const m = card.metrics[key];
      expect(m.pass, key).toBe(raw[key].pass);
      expect(m.value, key).toBeCloseTo(
        raw[key].unit === "%" ? raw[key].value / 100 : raw[key].value,
      );
    }
  });

  it("lists one red-team row per step, all with an actual verdict", () => {
    const steps = evalDetails.redteam_results.reduce((n, c) => n + c.steps.length, 0);
    expect(card.redteam).toHaveLength(steps);
    expect(card.redteam.every((r) => r.actual_verdict !== null)).toBe(true);
  });
});

describe("credit line (M016: 'Postpaid credit line mil sakti hai kya?')", () => {
  const first = toSendResult(turn(turnM016Credit));
  const offer = first.bot.find((b) => b.type === "loan-offer")?.offer;

  it("titles the card as a short-term credit line, not a business loan", () => {
    expect(offer?.product).toBe("credit_line");
    expect(offer?.title).toContain("₹7,000");
    expect(offer?.title).toContain("credit line");
    expect(offer?.title).not.toMatch(/लोन|loan/i);
  });

  it("shows the credit-line KFS before Haan/Nahi: limit, interest-free days, APR after due date, late fee, lender, grievance", () => {
    const rows = Object.fromEntries((offer?.kfsRows ?? []).map((r) => [r.label, r.value]));
    expect(rows["Credit limit"]).toBe("₹7,000");
    expect(rows["Interest-free period"]).toContain("30");
    expect(rows["After the due date"]).toBe("24% a year");
    expect(rows["Late fee"]).toBe("₹250");
    expect(rows["Repay on time"]).toContain("₹7,000");
    expect(rows["Lender"]).toContain("Demo NBFC");
    expect(rows["Grievance contact"]).toContain("grievance@");
    expect(offer?.pendingAuditId).toBe(
      String(turn(turnM016Credit).pending_confirmation?.pending_audit_id),
    );
  });

  it("marks the credit-line steps with their product in the trace", () => {
    const withProduct = first.trace.filter((r) => r.output.includes("product credit_line"));
    expect(withProduct.map((r) => r.agent)).toEqual(
      expect.arrayContaining(["Plan", "Guardrail", "Action"]),
    );
    const offerRow = first.trace.find(
      (r) => r.agent === "Guardrail" && r.output.startsWith("create_offer"),
    );
    expect(offerRow?.output).toContain("product credit_line");
    expect(offerRow?.reason).toContain("CONSENT_REQUIRED");
  });

  it("after haan: the loan-team brief says credit line, with interest-free days and late fee", () => {
    const after = toSendResult(turn(confirmM016Credit));
    expect(after.bot.at(-1)?.text).toMatch(/^Brief sent to the loan team · HO-\w+$/);
    const { detail } = toHandoffDetail(handoffCredit as unknown as ApiHandoffDetail, "Sh****");
    expect(detail.brief.loan?.product).toBe("credit_line");
    expect(detail.brief.loan?.interest_free_days).toBe(30);
    expect(detail.brief.loan?.late_fee_inr).toBe(250);
    expect(detail.brief.asked).toContain("credit line");
  });

  it("leaves the term-loan card unchanged", () => {
    const loan = toSendResult(turn(turnM001)).bot.find((b) => b.type === "loan-offer")?.offer;
    expect(loan?.product).toBe("term_loan");
    expect(loan?.title).toContain("लोन");
    expect(loan?.kfsRows.map((r) => r.label)).toContain("Total repayable");
  });
});

describe("shop insurance (simulated insurer)", () => {
  const offerOf = (t: unknown) =>
    toSendResult(turn(t)).bot.find((b) => b.type === "insurance-offer");

  it("M017 QR problem: ticket updated, then the device cover card below the agent's text", () => {
    const result = toSendResult(turn(turnM017Insurance));
    expect(result.bot.map((b) => b.type)).toEqual(["text", "insurance-offer"]);
    const ins = result.bot[1]?.insurance;
    expect(ins?.product_id).toBe("DEVICE_PROTECT");
    expect(ins?.cover_inr).toBe(15000);
    expect(ins?.premium_inr).toBe(499);
    expect(ins?.reasons).toContain("DEVICE_TICKET_HISTORY");
    expect(ins?.pendingAuditId).toBe(
      String(turn(turnM017Insurance).pending_confirmation?.pending_audit_id),
    );
    // never mistaken for a loan
    expect(result.bot.some((b) => b.type === "loan-offer")).toBe(false);
  });

  it("trace: check_insurance stays a small ALLOW, offer_insurance is a big CONSENT_REQUIRED", () => {
    const rows = toSendResult(turn(turnM017Insurance)).trace.filter((r) => r.agent === "Guardrail");
    const check = rows.find((r) => r.output.startsWith("check_insurance"));
    const offer = rows.find((r) => r.output.startsWith("offer_insurance"));
    expect(check?.verdict).toBe("ALLOW");
    expect(offer?.verdict).toBe("NEEDS_CONFIRMATION");
    expect(offer?.reason).toContain("CONSENT_REQUIRED");
    expect(offer?.big).toBe(true);
  });

  it("after yes: ALLOW CONFIRMED_BY_MERCHANT, an INS- reference, and a follow-up brief for the insurer", () => {
    const c = turn(confirmM017Insurance);
    const after = toSendResult(c);
    expect(after.bot.at(-1)?.text).toMatch(/^Brief sent to the insurer partner · HO-\w+$/);
    expect(c.actions.find((a) => a.action_type === "offer_insurance")?.ref_id).toMatch(/^INS-/);
    expect(after.trace.some((r) => r.reason?.startsWith("CONFIRMED_BY_MERCHANT"))).toBe(true);
    expect(after.trace.find((r) => r.agent === "Handoff")?.output).toContain("INSURANCE_INTEREST");
    const { detail } = toHandoffDetail(handoffInsurance as unknown as ApiHandoffDetail, "Ba****");
    expect(detail.brief.reason_code).toBe("INSURANCE_INTEREST");
    expect(detail.brief.suggested_step).toBeNull();
    expect(detail.brief.loan ?? null).toBeNull();
  });

  it("M004 asks for shop insurance: Electronics Parts & Stock Cover", () => {
    const ins = offerOf(turnM004Insurance)?.insurance;
    expect(ins?.product_name).toBe("Electronics Parts & Stock Cover");
    expect(ins?.cover_inr).toBe(650000);
    expect(ins?.premium_inr).toBe(5850);
  });

  it("abhi nahi: nothing is recorded and no card comes back", () => {
    const d = turn(declineM004Insurance);
    expect(d.actions).toEqual([]);
    expect(toSendResult(d).bot.map((b) => b.type)).toEqual(["text"]);
  });

  it("M002 (settlement still failed): offer BLOCKed as ISSUE_UNRESOLVED, shown big, no card", () => {
    const result = toSendResult(turn(turnM002Insurance));
    expect(result.bot.map((b) => b.type)).toEqual(["text"]);
    const block = result.trace.find((r) => r.verdict === "BLOCK");
    expect(block?.reason).toContain("ISSUE_UNRESOLVED");
    expect(block?.big).toBe(true);
  });

  it("M003 (nothing fits): just the agent's text", () => {
    expect(toSendResult(turn(turnM003Insurance)).bot.map((b) => b.type)).toEqual(["text"]);
  });

  it("insurance consent withdrawn: the next offer is BLOCKed (CONSENT_WITHDRAWN), no card", () => {
    const result = toSendResult(turn(turnM004Withdrawn));
    expect(offerOf(turnM004Withdrawn)).toBeUndefined();
    expect(result.trace.find((r) => r.verdict === "BLOCK")?.reason).toContain("CONSENT_WITHDRAWN");
  });

  it("the spec's mock TurnResponse renders the same card", () => {
    const sample = {
      session_id: "S-mock",
      turn_no: 1,
      trace_id: "T-mock",
      plan: [],
      actions: [],
      handoff: null,
      latency_ms: 0,
      cost_inr: 0,
      spans: [],
      ...(sampleInsurance as object),
    };
    const ins = offerOf(sample)?.insurance;
    expect(ins?.product_name).toBe("Soundbox / POS Device Protection");
    expect(ins?.pendingAuditId).toBe("42");
  });

  it("the loan card is untouched", () => {
    expect(toSendResult(turn(turnM001)).bot.map((b) => b.type)).toContain("loan-offer");
  });
});
