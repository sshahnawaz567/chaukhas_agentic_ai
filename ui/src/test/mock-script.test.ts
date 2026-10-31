import { beforeEach, describe, expect, it } from "vitest";

import {
  confirm,
  getAudit,
  getEvalLatest,
  createSession,
  getHandoff,
  getHandoffs,
  getMerchants,
  getRedteamAttacks,
  getTicketEvents,
  resetAgentDesk,
  resolveHandoff,
  redteamCheck,
  sendMessage,
} from "@/api/client";
import m001Json from "@/mocks/M001.json";
import m002Json from "@/mocks/M002.json";
import m005Json from "@/mocks/M005.json";
import merchantsJson from "@/mocks/merchants.json";
import redteamJson from "@/mocks/redteam.json";
import agentdeskJson from "@/mocks/agentdesk.json";
import { type MerchantScript, type Verdict } from "@/lib/chaukas-types";

const SCRIPTS: MerchantScript[] = [m001Json, m002Json, m005Json] as unknown as MerchantScript[];
const VERDICTS: Verdict[] = ["ALLOW", "NEEDS_CONFIRMATION", "BLOCK"];
const AGENTS = ["Intent", "Context", "Plan", "Guardrail", "Action", "Reply", "Handoff"];

// Mock data rules behind the scripted demo: every merchant the UI lists must have
// a script, every loan offer must be confirmable, and every trace step must be
// renderable by the TracePanel.
describe("Mock script data", () => {
  it("has a script for every merchant listed in merchants.json", () => {
    const scriptIds = new Set(SCRIPTS.map((s) => s.merchantId));
    for (const merchant of merchantsJson as { id: string }[]) {
      expect(scriptIds.has(merchant.id), merchant.id).toBe(true);
    }
  });

  it("gives every script at least one turn and quick replies", () => {
    for (const script of SCRIPTS) {
      expect(script.turns.length).toBeGreaterThan(0);
      expect(script.quickReplies.length).toBeGreaterThan(0);
    }
  });

  it("pairs every loan offer with a consent script and a unique pending audit id", () => {
    const auditIds = new Set<string>();
    for (const script of SCRIPTS) {
      for (const turn of script.turns) {
        for (const el of turn.bot) {
          if (el.type === "loan-offer" && el.offer) {
            expect(el.offer.pendingAuditId).toMatch(/^\d+$/); // an audit_log id
            expect(auditIds.has(el.offer.pendingAuditId)).toBe(false);
            auditIds.add(el.offer.pendingAuditId);
            expect(script.consent).toBeDefined();
          }
        }
      }
      if (script.consent) {
        expect(script.consent.approve.trace.verdict).toBe("ALLOW");
        // DENY writes no new guardrail decision (CONTRACTS C2 rule 5) — the offer
        // is dropped, so the decline row must not carry a verdict.
        expect(script.consent.decline.trace.verdict).toBeUndefined();
      }
    }
  });

  it("keeps trace rows renderable: valid agent, verdict, latency and cost", () => {
    for (const script of SCRIPTS) {
      const rows = [
        ...script.turns.flatMap((turn) => turn.trace),
        ...(script.consent ? [script.consent.approve.trace, script.consent.decline.trace] : []),
      ];
      for (const row of rows) {
        expect(AGENTS).toContain(row.agent);
        if (row.verdict) expect(VERDICTS).toContain(row.verdict);
        expect(row.latencyMs).toBeGreaterThanOrEqual(0);
        expect(row.cost).toMatch(/^₹/);
      }
    }
  });
});

// Client behavior in mock mode: sessions track turns, offers become confirmable,
// consent resolves to the scripted outcome.
describe("Mock client flow", () => {
  it("scripts turns in order and falls back after they run out", async () => {
    const merchants = await getMerchants();
    expect(merchants.map((m) => m.id)).toContain("M001");

    const session = await createSession("M001");
    expect(session.greetingText.length).toBeGreaterThan(0);

    const first = await sendMessage(session.id, "पैसा नहीं आया");
    expect(first.bot.length).toBeGreaterThan(0);
    expect(first.trace.length).toBeGreaterThan(0);

    const after = await sendMessage(session.id, "anything else");
    expect(after.bot[0]?.type).toBe("text");
    expect(after.trace[0]?.agent).toBe("Intent");
  });

  it("records consent for a pending loan offer", async () => {
    const session = await createSession("M001");
    await sendMessage(session.id, "पैसा नहीं आया");

    const result = await confirm(session.id, "9003", true);
    expect(result.offerState).toBe("consented");
    expect(result.trace[0]?.verdict).toBe("ALLOW");

    // Consumed pending audits are not confirmable twice.
    await expect(confirm(session.id, "9003", true)).rejects.toThrow();
  });
});

// Red-team panel (demo scene 4B): every pre-filled attack must be BLOCKed with a
// reason code that exists in CONTRACTS C1, and the mock must answer for it.
const REASON_CODES = [
  "WITHIN_POLICY",
  "CONFIRMED_BY_MERCHANT",
  "APPROVED_BY_HUMAN",
  "NOT_IN_ALLOW_LIST",
  "ACTION_DISABLED",
  "NEVER_ALLOWED",
  "INVALID_PARAMS",
  "LEDGER_MISMATCH",
  "NOT_RETRIGGERABLE",
  "DUPLICATE_ACTION",
  "OVER_AUTO_LIMIT",
  "OVER_DAILY_LIMIT",
  "CONSENT_REQUIRED",
  "OFFER_NOT_ELIGIBLE",
  "ISSUE_UNRESOLVED",
  "OFFER_COOLING_OFF",
];

describe("Red-team mock", () => {
  it("blocks every attack with a contract reason code and an audit id", async () => {
    const attacks = await getRedteamAttacks();
    expect(attacks.length).toBeGreaterThanOrEqual(2);
    for (const attack of attacks) {
      const decision = await redteamCheck(attack.merchant_id, attack.step);
      expect(decision.verdict, attack.id).toBe("BLOCK");
      expect(REASON_CODES).toContain(decision.reason_code);
      expect(decision.audit_id).not.toBeNull();
      expect(decision.rollback_token).toBeNull();
    }
  });

  it("has a decision for every attack and no orphan decisions", () => {
    const ids = redteamJson.attacks.map((a) => a.id).sort();
    expect(Object.keys(redteamJson.decisions).sort()).toEqual(ids);
  });

  it("rejects a step that was not scripted", async () => {
    const [attack] = await getRedteamAttacks();
    const tampered = { ...attack!.step, amount: 1 };
    await expect(redteamCheck(attack!.merchant_id, tampered)).rejects.toThrow();
  });
});

// Agent-desk (demo scene 3): the human's approval goes back through the guardrail
// and the ticket timeline records who did what.
describe("Agent-desk mock", () => {
  beforeEach(() => resetAgentDesk());

  it("starts with an open M002 handoff carrying a full brief", async () => {
    const open = await getHandoffs("open");
    expect(open.map((h) => h.id)).toContain("HO-10021");

    const detail = await getHandoff("HO-10021");
    expect(detail.merchant_id).toBe("M002");
    expect(detail.brief.refused[0]?.reason_code).toBe("OVER_AUTO_LIMIT");
    expect(detail.brief.suggested_step?.amount).toBe(32500);
    expect(detail.brief.decision_needed.length).toBeGreaterThan(0);
  });

  it("approve: guardrail ALLOW as APPROVED_BY_HUMAN, payout runs, timeline names the staff id", async () => {
    const before = await getTicketEvents("TKT-77201");
    const result = await resolveHandoff("HO-10021", "STAFF-042", true);

    expect(result.decision?.verdict).toBe("ALLOW");
    expect(result.decision?.reason_code).toBe("APPROVED_BY_HUMAN");
    expect(result.action_result?.status).toBe("success");
    expect(result.handoff.status).toBe("resolved");

    const after = await getTicketEvents("TKT-77201");
    expect(after.length).toBeGreaterThan(before.length);
    const human = after.find((e) => e.actor === "human");
    expect(human?.actor_id).toBe("STAFF-042");

    expect((await getHandoffs("open")).map((h) => h.id)).not.toContain("HO-10021");
    await expect(resolveHandoff("HO-10021", "STAFF-042", true)).rejects.toThrow();
  });

  it("decline: nothing executes", async () => {
    const result = await resolveHandoff("HO-10021", "STAFF-042", false);
    expect(result.decision ?? null).toBeNull();
    expect(result.action_result ?? null).toBeNull();
  });

  it("keeps the scene-3 payout handoff first in the queue", async () => {
    expect((await getHandoffs("open"))[0]?.id).toBe("HO-10021");
  });

  it("loan follow-up: the brief carries the accepted offer and the KFS the merchant saw", async () => {
    const detail = await getHandoff("HO-10022");
    const loan = detail.brief.loan;
    expect(detail.brief.reason_code).toBe("LOAN_ACCEPTED");
    expect(detail.brief.suggested_step).toBeNull();
    expect(loan?.amount).toBe(50000);
    // KFS arithmetic: total repayable can never be less than the amount plus the fee.
    expect(loan!.total_repayable_inr).toBeGreaterThanOrEqual(
      loan!.amount + loan!.processing_fee_inr,
    );
    expect(loan?.consent_audit_id).toBe(9004);
  });

  it("loan follow-up: marking it done executes nothing and records the note", async () => {
    const result = await resolveHandoff("HO-10022", "STAFF-042", false, "loan follow-up done");
    expect(result.decision ?? null).toBeNull();
    expect(result.action_result ?? null).toBeNull();
    expect(result.handoff.status).toBe("resolved");
    expect(result.handoff.human_decision).toBe("loan follow-up done");
    // The payout handoff is untouched.
    expect((await getHandoff("HO-10021")).status).toBe("open");
  });
});

describe("Loan consent → agent desk", () => {
  it("saying haan to the offer tells the merchant a brief went to the loan team", async () => {
    const session = await createSession("M001");
    await sendMessage(session.id, "पैसा नहीं आया");
    const result = await confirm(session.id, "9003", true);
    expect(result.handoffNote).toContain("HO-10022");
  });

  it("saying abhi nahi sends nothing to the desk", async () => {
    const session = await createSession("M001");
    await sendMessage(session.id, "पैसा नहीं आया");
    const result = await confirm(session.id, "9003", false);
    expect(result.handoffNote).toBeUndefined();
  });
});

// Proof (demo scene 5): the audit mock must obey the same rules the database
// enforces, and the scorecard mock must never contain invented numbers.
describe("Audit mock", () => {
  it("uses contract reason codes and only executes ALLOWed rows (executions_require_allow)", async () => {
    const rows = await getAudit();
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(REASON_CODES, String(row.id)).toContain(row.reason_code);
      if (row.guardrail_decision !== "ALLOW")
        expect(row.execution_status, String(row.id)).toBeNull();
    }
  });

  it("links every confirmation to a NEEDS_CONFIRMATION row for the same action and amount", async () => {
    const rows = await getAudit();
    const byId = new Map(rows.map((r) => [r.id, r]));
    for (const row of rows.filter((r) => r.confirms_audit_id !== null)) {
      const pending = byId.get(row.confirms_audit_id!);
      expect(pending?.guardrail_decision, String(row.id)).toBe("NEEDS_CONFIRMATION");
      expect(pending?.action_type).toBe(row.action_type);
      expect(pending?.amount).toBe(row.amount);
      expect(pending!.id).toBeLessThan(row.id);
    }
  });

  it("agrees with the red-team and agent-desk mocks on audit ids", async () => {
    const byId = new Map((await getAudit()).map((r) => [r.id, r]));
    for (const decision of Object.values(redteamJson.decisions)) {
      expect(byId.get(decision.audit_id)?.reason_code).toBe(decision.reason_code);
    }
    const approval = agentdeskJson.resolve.approve.decision;
    expect(byId.get(approval.audit_id)?.reason_code).toBe(approval.reason_code);
  });

  it("filters by merchant", async () => {
    const rows = await getAudit({ merchant_id: "M002" });
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((r) => r.merchant_id === "M002")).toBe(true);
  });
});

describe("Eval scorecard mock", () => {
  it("is a placeholder: no invented values or results", async () => {
    const card = await getEvalLatest();
    expect(card.run_at).toBeNull();
    for (const metric of Object.values(card.metrics)) {
      expect(metric.value).toBeNull();
      expect(metric.pass).toBeNull();
    }
    for (const c of card.redteam) {
      expect(c.actual_verdict).toBeNull();
      expect(REASON_CODES).toContain(c.expected_reason_code);
    }
  });
});

describe("Chat trace vs audit log", () => {
  it("every guardrail row in a chat trace points at a matching audit row", async () => {
    const byId = new Map((await getAudit()).map((r) => [r.id, r]));
    const rows = SCRIPTS.flatMap((script) => [
      ...script.turns.flatMap((turn) => turn.trace),
      ...(script.consent ? [script.consent.approve.trace] : []),
    ]);
    const guarded = rows.filter((row) => row.agent === "Guardrail");
    expect(guarded.length).toBeGreaterThan(0);
    for (const row of guarded) {
      const id = Number(/audit #(\d+)/.exec(row.output)?.[1]);
      const audit = byId.get(id);
      expect(audit, row.output).toBeDefined();
      expect(audit?.guardrail_decision).toBe(row.verdict);
      expect(row.reason?.startsWith(audit!.reason_code), row.output).toBe(true);
    }
  });
});
