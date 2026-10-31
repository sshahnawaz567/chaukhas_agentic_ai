import { useCallback, useEffect, useState } from "react";
import { formatDistanceToNowStrict } from "date-fns";
import {
  Bot,
  CheckCircle2,
  CircleDot,
  Inbox,
  RotateCcw,
  ShieldAlert,
  ShieldPlus,
  UserRound,
  Wrench,
  XCircle,
} from "lucide-react";

import {
  USE_MOCK,
  getHandoff,
  getHandoffs,
  getTicketEvents,
  resetAgentDesk,
  resolveHandoff,
} from "@/api/client";
import type {
  HandoffDetail,
  HandoffSummary,
  LoanFollowUp,
  ResolveResult,
  TicketActor,
  TicketEvent,
  Verdict,
} from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

import { StepCall } from "./StepCall";
import { VerdictPill, verdictBorderClasses } from "./VerdictPill";

const ago = (iso: string) => `${formatDistanceToNowStrict(new Date(iso))} ago`;

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
      {children}
    </div>
  );
}

// --- Queue -------------------------------------------------------------------

function Queue({
  items,
  selectedId,
  onSelect,
}: {
  items: HandoffSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3">
        <Inbox className="size-5 text-navy" />
        <h2 className="text-lg font-extrabold text-ink">Handoff queue</h2>
        <span className="ml-auto rounded-full bg-muted px-2.5 py-0.5 text-sm font-semibold text-foreground">
          {items.filter((h) => h.status !== "resolved").length} open
        </span>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {items.length === 0 && (
          <p className="p-4 text-center text-base text-muted-foreground">No handoffs right now.</p>
        )}
        {items.map((item) => {
          const resolved = item.status === "resolved";
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              className={cn(
                "w-full rounded-xl border p-3 text-left transition-colors",
                item.id === selectedId
                  ? "border-navy bg-accent"
                  : "border-border bg-card hover:bg-surface",
                resolved && "opacity-70",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-ink">{item.id}</span>
                {item.reason_code === "INSURANCE_INTEREST" && (
                  <span className="rounded-full bg-teal-600 px-2 py-0.5 text-xs font-bold text-primary-foreground">
                    Insurance interest
                  </span>
                )}
                <span className="text-sm text-muted-foreground">· {item.merchant_id}</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {ago(item.created_at)}
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <VerdictPill
                  tone={
                    resolved
                      ? "ALLOW"
                      : item.reason_code === "SUSPECTED_INJECTION"
                        ? "BLOCK"
                        : "NEEDS_CONFIRMATION"
                  }
                >
                  {resolved ? "resolved" : "open"}
                </VerdictPill>
                <span className="font-mono text-xs font-semibold text-foreground">
                  {item.reason_code}
                </span>
              </div>
              <p className="mt-1.5 text-sm leading-snug text-foreground">{item.decision_needed}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// --- Brief + approve ------------------------------------------------------------

const inr = (amount: number) => `₹${amount.toLocaleString("en-IN")}`;
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";

/** The accepted offer and the exact Key Fact Statement the merchant saw before saying haan. */
function LoanDetails({ loan }: { loan: LoanFollowUp }) {
  const credit = loan.product === "credit_line";
  const productRows: [string, string][] = credit
    ? [
        ["Credit limit", inr(loan.amount)],
        [
          "Interest-free period",
          loan.interest_free_days != null
            ? `${loan.interest_free_days} days, no interest/fee`
            : "—",
        ],
        ["After the due date", `${loan.apr_pct}% a year`],
        ["Late fee", loan.late_fee_inr != null ? inr(loan.late_fee_inr) : "—"],
        ["Processing fee", inr(loan.processing_fee_inr)],
        ["Repay on time", `${inr(loan.total_repayable_inr)} in one billing cycle`],
      ]
    : [
        ["Loan amount", inr(loan.amount)],
        ["APR", `${loan.apr_pct}% a year`],
        ["Processing fee", inr(loan.processing_fee_inr)],
        ["Tenure", `${loan.tenure_months} months`],
        ["Total repayable", inr(loan.total_repayable_inr)],
      ];
  const rows: [string, string][] = [
    ["Offer", loan.offer_id],
    ["Lender", loan.lender_name],
    ...productRows,
    ["Grievance contact", loan.grievance_contact],
    ["KFS shown", when(loan.kfs_shown_at)],
    [
      "Consent",
      `${when(loan.consent_at)}${loan.consent_audit_id != null ? ` · audit #${loan.consent_audit_id}` : ""}`,
    ],
  ];
  return (
    <div>
      <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-allow/40 bg-allow/10 px-3 py-1 text-sm font-bold text-allow">
        <CheckCircle2 className="size-4" />
        {credit ? "Credit line accepted" : "Business loan accepted"}
      </div>
      <SectionLabel>
        {credit ? "Credit line details" : "Loan details"} — as shown to the merchant
      </SectionLabel>
      <dl className="mt-1.5 divide-y divide-border overflow-hidden rounded-xl border border-border">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-4 px-3.5 py-2">
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="text-right text-base font-semibold tabular-nums text-foreground">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ResolveOutcome({ result, staffId }: { result: ResolveResult; staffId: string }) {
  const { decision, action_result: action } = result;

  if (!decision) {
    return (
      <div className="trace-in rounded-2xl border-l-4 border-border bg-muted/50 p-4">
        <div className="text-lg font-extrabold text-ink">Closed by {staffId}</div>
        <p className="mt-1 text-base text-muted-foreground">
          Nothing was executed. Handoff {result.handoff.id} closed
          {result.handoff.human_decision ? ` · ${result.handoff.human_decision}` : ""}.
        </p>
      </div>
    );
  }

  const verdict = decision.verdict as Verdict;
  return (
    <div className="space-y-2.5">
      <div
        className={cn(
          "trace-in rounded-2xl border-l-4 p-4 shadow-[var(--shadow-soft)]",
          verdictBorderClasses[verdict],
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold uppercase tracking-wide text-foreground">
            Guardrail
          </span>
          <VerdictPill tone={verdict} className="px-3 py-1 text-sm">
            {verdict}
          </VerdictPill>
          <span className="font-mono text-xs text-muted-foreground">
            actor human · {staffId} · audit #{decision.audit_id ?? "—"}
          </span>
        </div>
        <div className="mt-1.5 text-xl font-extrabold text-ink">{decision.reason_code}</div>
        <p className="mt-0.5 text-base text-foreground">{decision.reason}</p>
      </div>
      {action && (
        <div className="trace-in flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-border bg-surface px-4 py-3">
          {action.status === "success" ? (
            <CheckCircle2 className="size-5 text-allow" />
          ) : (
            <XCircle className="size-5 text-block" />
          )}
          <span className="text-base font-bold text-foreground">{action.action_type}</span>
          <span className="text-base text-foreground">
            {action.status} · {action.ref_id}
          </span>
          <span className="ml-auto font-mono text-xs text-muted-foreground">
            {action.latency_ms} ms
          </span>
        </div>
      )}
      <p className="text-sm font-semibold text-muted-foreground">
        {result.handoff.status === "resolved"
          ? `Handoff ${result.handoff.id} resolved.`
          : verdict === "BLOCK"
            ? `Nothing was executed. BLOCK is final — handoff ${result.handoff.id} stays open.`
            : `Not executed — handoff ${result.handoff.id} stays open.`}
      </p>
    </div>
  );
}

function BriefCard({
  detail,
  result,
  busy,
  onResolve,
}: {
  detail: HandoffDetail;
  result: ResolveResult | undefined;
  busy: boolean;
  onResolve: (staffId: string, approve: boolean, note?: string) => void;
}) {
  const [staffId, setStaffId] = useState("STAFF-042");
  const { brief } = detail;
  const resolved = detail.status === "resolved";
  const insurance = brief.reason_code === "INSURANCE_INTEREST";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-5 py-3">
        <h2 className="text-lg font-extrabold text-ink">Decision brief</h2>
        <span className="font-mono text-sm text-muted-foreground">
          {detail.id} · {detail.merchant_id} {detail.merchant_name_masked} · trace {detail.trace_id}
        </span>
        <span className="ml-auto rounded-full bg-surface px-3 py-1 text-sm font-semibold text-navy">
          confidence {Math.round(brief.confidence * 100)}%
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {brief.reason_code === "SUSPECTED_INJECTION" && (
          <div className="flex items-start gap-3 rounded-2xl border-l-4 border-block bg-block/10 p-4">
            <ShieldAlert className="mt-0.5 size-6 shrink-0 text-block" />
            <div>
              <div className="text-lg font-extrabold text-ink">
                Possible fraud — prompt injection
              </div>
              <p className="mt-0.5 text-base text-foreground">
                The message tried to give the AI orders. Caught by a code check before any model saw
                it. Nothing was executed and no money action is pending — review the merchant, do
                not approve anything.
              </p>
            </div>
          </div>
        )}

        <div>
          <SectionLabel>Asked</SectionLabel>
          <p className="mt-1 text-lg font-semibold text-ink">{brief.asked}</p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <SectionLabel>Verified</SectionLabel>
            <ul className="mt-1.5 space-y-1">
              {brief.verified.map((fact) => (
                <li key={fact} className="flex items-start gap-2 text-base text-foreground">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-allow" />
                  {fact}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <SectionLabel>Done</SectionLabel>
            <ul className="mt-1.5 space-y-1">
              {brief.done.map((item) => (
                <li key={item} className="flex items-start gap-2 text-base text-foreground">
                  <Wrench className="mt-0.5 size-4 shrink-0 text-navy" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div>
          <SectionLabel>Refused — and why</SectionLabel>
          <div className="mt-1.5 space-y-1.5">
            {brief.refused.map((step) => (
              <div
                key={`${step.action_type}-${step.reason_code}`}
                className={cn(
                  "rounded-xl border-l-4 px-3.5 py-2.5",
                  verdictBorderClasses[step.verdict],
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <VerdictPill tone={step.verdict}>{step.verdict}</VerdictPill>
                  <span className="font-mono text-sm font-bold text-foreground">
                    {step.action_type}
                  </span>
                  <span className="font-mono text-sm text-foreground">{step.reason_code}</span>
                </div>
                <p className="mt-1 text-base font-semibold text-ink">{step.reason}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl bg-navy p-4 text-primary-foreground">
          <div className="text-xs font-bold uppercase tracking-widest text-primary-foreground/70">
            Decision needed
          </div>
          <p className="mt-1 text-xl font-extrabold leading-snug">{brief.decision_needed}</p>
        </div>

        {brief.loan && <LoanDetails loan={brief.loan} />}
        {insurance && (
          <div className="flex items-start gap-3 rounded-2xl border-l-4 border-teal-600 bg-teal-50 p-4">
            <ShieldPlus className="mt-0.5 size-6 shrink-0 text-teal-700" />
            <div>
              <div className="text-lg font-extrabold text-ink">
                Insurance interest — a follow-up
              </div>
              <p className="mt-0.5 text-base text-foreground">
                The merchant said yes to hearing from the insurer. Not an approval: no premium was
                charged and no policy was issued. Pass it to the insurer partner, then mark it done.
              </p>
            </div>
          </div>
        )}

        {brief.suggested_step && (
          <div>
            <SectionLabel>Suggested action</SectionLabel>
            <div className="mt-1.5">
              <StepCall step={brief.suggested_step} />
            </div>
          </div>
        )}

        {result ? (
          <ResolveOutcome result={result} staffId={result.handoff.assigned_to} />
        ) : resolved ? (
          <p className="text-base font-semibold text-muted-foreground">
            This handoff is already resolved.
          </p>
        ) : (
          <div className="space-y-2.5 rounded-2xl border border-border bg-surface p-4">
            <div className="flex flex-wrap items-center gap-2.5">
              <label htmlFor="staff-id" className="text-base font-semibold text-foreground">
                Staff id
              </label>
              <input
                id="staff-id"
                value={staffId}
                onChange={(event) => setStaffId(event.target.value)}
                className="w-40 rounded-xl border border-input bg-background px-3 py-2 font-mono text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              {/* Nothing to execute (e.g. the merchant asked for a human): the desk can only close it. */}
              {brief.suggested_step && (
                <button
                  type="button"
                  disabled={busy || !staffId.trim()}
                  onClick={() => onResolve(staffId.trim(), true)}
                  className="rounded-xl bg-navy px-5 py-2.5 text-base font-semibold text-primary-foreground transition-colors hover:bg-navy/90 disabled:opacity-50"
                >
                  Approve &amp; execute
                </button>
              )}
              <button
                type="button"
                disabled={busy || !staffId.trim()}
                onClick={() =>
                  onResolve(
                    staffId.trim(),
                    false,
                    brief.loan
                      ? `loan follow-up done for ${brief.loan.offer_id}`
                      : insurance
                        ? "insurance follow-up done"
                        : undefined,
                  )
                }
                className="rounded-xl border border-border bg-card px-5 py-2.5 text-base font-semibold text-foreground transition-colors hover:bg-accent disabled:opacity-50"
              >
                {brief.suggested_step
                  ? "Decline"
                  : brief.loan || insurance
                    ? "Mark followed up"
                    : "Close without action"}
              </button>
            </div>
            <p className="text-sm text-muted-foreground">
              Your approval still goes through the guardrail. Checks 1–7 re-run — a BLOCK can never
              be overridden, by anyone.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Ticket timeline -----------------------------------------------------------

const actorStyle: Record<TicketActor, { label: string; className: string; Icon: typeof Bot }> = {
  system: { label: "System", className: "bg-muted text-muted-foreground", Icon: CircleDot },
  agent: { label: "AI agent", className: "bg-cyan/15 text-navy", Icon: Bot },
  human: { label: "Human", className: "bg-navy text-primary-foreground", Icon: UserRound },
  merchant: { label: "Merchant", className: "bg-accent text-navy", Icon: UserRound },
};

function Timeline({ ticketId, events }: { ticketId: string | null; events: TicketEvent[] }) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <h2 className="text-lg font-extrabold text-ink">Ticket timeline</h2>
        <div className="font-mono text-xs text-muted-foreground">{ticketId ?? "no ticket"}</div>
      </div>
      <ol className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {events.map((event) => {
          const style = actorStyle[event.actor];
          return (
            <li
              key={event.id}
              className={cn(
                "trace-in rounded-xl border p-3",
                event.actor === "human" ? "border-navy bg-accent" : "border-border bg-card",
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide",
                    style.className,
                  )}
                >
                  <style.Icon className="size-3.5" />
                  {style.label}
                  {event.actor_id ? ` · ${event.actor_id}` : ""}
                </span>
                <span className="font-mono text-xs text-muted-foreground">{event.event_type}</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {ago(event.created_at)}
                </span>
              </div>
              <p className="mt-1.5 text-base leading-snug text-foreground">{event.detail}</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// --- Agent desk ------------------------------------------------------------------

export function AgentDesk() {
  const [queue, setQueue] = useState<HandoffSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<HandoffDetail | null>(null);
  const [events, setEvents] = useState<TicketEvent[]>([]);
  const [results, setResults] = useState<Record<string, ResolveResult>>({});
  const [busy, setBusy] = useState(false);

  const loadQueue = useCallback(async () => {
    const items = await getHandoffs();
    setQueue(items);
    setSelectedId(
      (current) =>
        current ?? items.find((h) => h.status !== "resolved")?.id ?? items[0]?.id ?? null,
    );
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    const handoff = await getHandoff(id);
    setDetail(handoff);
    setEvents(handoff.ticket_id ? await getTicketEvents(handoff.ticket_id) : []);
  }, []);

  useEffect(() => {
    loadQueue().catch((error) => console.error("getHandoffs failed", error));
  }, [loadQueue]);

  useEffect(() => {
    if (!selectedId) return;
    loadDetail(selectedId).catch((error) => console.error("getHandoff failed", error));
  }, [selectedId, loadDetail]);

  const resolve = async (staffId: string, approve: boolean, note?: string) => {
    if (!detail || busy) return;
    setBusy(true);
    try {
      const result = await resolveHandoff(detail.id, staffId, approve, note);
      setResults((prev) => ({ ...prev, [detail.id]: result }));
      await Promise.all([loadQueue(), loadDetail(detail.id)]);
    } catch (error) {
      console.error("resolveHandoff failed", error);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    resetAgentDesk();
    setResults({});
    setSelectedId(null);
    setDetail(null);
    await loadQueue();
  };

  return (
    <div className="flex h-full flex-col gap-3">
      {USE_MOCK && (
        <div className="flex shrink-0 justify-end">
          <button
            type="button"
            onClick={reset}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className="size-3.5" />
            Reset demo
          </button>
        </div>
      )}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,2fr)_minmax(0,1.2fr)]">
        <Queue items={queue} selectedId={selectedId} onSelect={setSelectedId} />
        {detail ? (
          <BriefCard
            key={detail.id}
            detail={detail}
            result={results[detail.id]}
            busy={busy}
            onResolve={resolve}
          />
        ) : (
          <div className="flex items-center justify-center rounded-2xl border border-dashed border-border text-base text-muted-foreground">
            Select a handoff
          </div>
        )}
        <Timeline ticketId={detail?.ticket_id ?? null} events={events} />
      </div>
    </div>
  );
}
