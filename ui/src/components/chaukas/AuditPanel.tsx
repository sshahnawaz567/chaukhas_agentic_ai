import { useEffect, useState } from "react";
import { CheckCircle2, Lock, Minus, XCircle } from "lucide-react";

import { getAudit } from "@/api/client";
import type { AuditRow, ExecutionStatus, TicketActor, Verdict } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

import { VerdictPill } from "./VerdictPill";

const VERDICTS: Verdict[] = ["ALLOW", "NEEDS_CONFIRMATION", "BLOCK"];

const actorClasses: Record<TicketActor, string> = {
  agent: "bg-cyan/15 text-navy",
  merchant: "bg-accent text-navy",
  human: "bg-navy text-primary-foreground",
  system: "bg-muted text-muted-foreground",
};

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

const rupees = (amount: number | null) =>
  amount === null ? "—" : `₹${amount.toLocaleString("en-IN")}`;

function Execution({ status }: { status: ExecutionStatus | null }) {
  if (status === null) {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
        <Minus className="size-4" />
        not executed
      </span>
    );
  }
  const ok = status === "success";
  return (
    <span className="inline-flex items-center gap-1 text-sm font-semibold text-foreground">
      {ok ? (
        <CheckCircle2 className="size-4 text-allow" />
      ) : (
        <XCircle className="size-4 text-block" />
      )}
      {status}
    </span>
  );
}

export function AuditPanel() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [filter, setFilter] = useState<Verdict | "ALL">("ALL");

  useEffect(() => {
    getAudit()
      .then(setRows)
      .catch((error) => console.error("getAudit failed", error));
  }, []);

  const counts = Object.fromEntries(
    VERDICTS.map((v) => [v, rows.filter((r) => r.guardrail_decision === v).length]),
  ) as Record<Verdict, number>;
  const visible = filter === "ALL" ? rows : rows.filter((r) => r.guardrail_decision === filter);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex shrink-0 flex-wrap items-center gap-4 border-b border-border px-6 py-4">
        <span className="flex size-11 items-center justify-center rounded-xl bg-navy text-primary-foreground">
          <Lock className="size-5" />
        </span>
        <div>
          <h2 className="text-xl font-extrabold text-ink">Audit log</h2>
          <p className="text-base text-muted-foreground">
            Every guardrail decision, with its reason. Append-only — a database trigger rejects
            every UPDATE and DELETE.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2" role="group" aria-label="Filter by decision">
          {(["ALL", ...VERDICTS] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setFilter(option)}
              aria-pressed={filter === option}
              className={cn(
                "inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors",
                filter === option
                  ? "border-navy bg-navy text-primary-foreground"
                  : "border-border bg-card text-foreground hover:bg-accent",
              )}
            >
              {option === "ALL" ? "All" : option}
              <span className="tabular-nums">
                {option === "ALL" ? rows.length : counts[option]}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
              <th className="px-4 py-3">#</th>
              <th className="px-4 py-3">Time</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Merchant</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3 text-right">Amount</th>
              <th className="px-4 py-3">Decision</th>
              <th className="px-4 py-3">Reason</th>
              <th className="px-4 py-3">Execution</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.id} className="border-t border-border align-top hover:bg-surface/60">
                <td className="px-4 py-3 font-mono text-sm tabular-nums text-muted-foreground">
                  {row.id}
                </td>
                <td className="px-4 py-3 font-mono text-sm tabular-nums text-foreground">
                  {time(row.ts)}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide",
                      actorClasses[row.actor],
                    )}
                  >
                    {row.actor}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-sm text-foreground">
                  {row.merchant_id ?? "—"}
                </td>
                <td className="px-4 py-3 font-mono text-sm font-semibold text-foreground">
                  {row.action_type}
                </td>
                <td className="px-4 py-3 text-right text-base font-semibold tabular-nums text-foreground">
                  {rupees(row.amount)}
                </td>
                <td className="px-4 py-3">
                  <VerdictPill tone={row.guardrail_decision}>{row.guardrail_decision}</VerdictPill>
                </td>
                <td className="px-4 py-3">
                  <div className="font-mono text-sm font-bold text-ink">{row.reason_code}</div>
                  <div className="text-sm text-muted-foreground">
                    {row.reason}
                    {row.confirms_audit_id !== null && (
                      <span className="font-mono"> · confirms #{row.confirms_audit_id}</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Execution status={row.execution_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <p className="p-8 text-center text-base text-muted-foreground">
            No decisions match this filter.
          </p>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-6 py-3 text-sm text-muted-foreground">
        Amounts and ids only — no personal data is ever written to the audit log. Rows without an
        ALLOW can never have an execution: the database enforces that too.
      </div>
    </div>
  );
}
