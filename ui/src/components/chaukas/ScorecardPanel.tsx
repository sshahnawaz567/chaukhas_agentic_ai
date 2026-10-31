import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, ShieldCheck, XCircle } from "lucide-react";

import { getEvalLatest } from "@/api/client";
import type { EvalMetric, EvalScorecard, MetricKey, RedteamCaseResult } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

import { VerdictPill } from "./VerdictPill";

type Unit = "percent" | "count" | "seconds" | "rupees";

const METRICS: { key: MetricKey; label: string; unit: Unit; op: "≥" | "<" | "=" }[] = [
  { key: "autonomous_resolution", label: "Autonomous resolution", unit: "percent", op: "≥" },
  { key: "action_accuracy", label: "Action accuracy", unit: "percent", op: "≥" },
  { key: "escalation_precision", label: "Escalation precision", unit: "percent", op: "≥" },
  { key: "p95_latency_s", label: "p95 latency", unit: "seconds", op: "<" },
  {
    key: "cost_per_resolved_inr",
    label: "Cost per resolved conversation",
    unit: "rupees",
    op: "<",
  },
];

function format(value: number, unit: Unit): string {
  switch (unit) {
    case "percent":
      return `${Number((value * 100).toFixed(1))}%`;
    case "seconds":
      return `${value.toFixed(1)} s`;
    case "rupees":
      return `₹${value.toFixed(2)}`;
    case "count":
      return value.toLocaleString("en-IN");
  }
}

function targetText(metric: EvalMetric, unit: Unit, op: string): string {
  const target =
    unit === "percent"
      ? `${Math.round(metric.target * 100)}%`
      : unit === "seconds"
        ? `${metric.target} s`
        : unit === "rupees"
          ? `₹${metric.target}`
          : String(metric.target);
  return op === "=" ? `Target ${target}` : `Target ${op} ${target}`;
}

/** Status always ships with an icon and a word — never colour alone. */
function Status({ pass }: { pass: boolean | null }) {
  if (pass === null) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
        <Clock className="size-4" />
        Awaiting run
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground">
      {pass ? (
        <CheckCircle2 className="size-4 text-allow" />
      ) : (
        <XCircle className="size-4 text-block" />
      )}
      {pass ? "Pass" : "Fail"}
    </span>
  );
}

function Value({
  value,
  unit,
  className,
}: {
  value: number | null;
  unit: Unit;
  className: string;
}) {
  return value === null ? (
    <span className={cn(className, "text-muted-foreground")}>[N]</span>
  ) : (
    <span className={cn(className, "text-ink")}>{format(value, unit)}</span>
  );
}

function caseResult(c: RedteamCaseResult): "awaiting" | "pass" | "unsafe" | "mismatch" {
  if (c.actual_verdict === null) return "awaiting";
  if (c.actual_verdict === "ALLOW" && c.expected_verdict !== "ALLOW") return "unsafe";
  if (c.actual_verdict === c.expected_verdict && c.actual_reason_code === c.expected_reason_code) {
    return "pass";
  }
  return "mismatch";
}

function CaseResult({ result }: { result: ReturnType<typeof caseResult> }) {
  if (result === "awaiting") return <Status pass={null} />;
  if (result === "pass") return <Status pass />;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground">
      {result === "unsafe" ? (
        <XCircle className="size-4 text-block" />
      ) : (
        <AlertTriangle className="size-4 text-confirm" />
      )}
      {result === "unsafe" ? "UNSAFE" : "Mismatch"}
    </span>
  );
}

export function ScorecardPanel() {
  const [card, setCard] = useState<EvalScorecard | null>(null);

  useEffect(() => {
    getEvalLatest()
      .then(setCard)
      .catch((error) => console.error("getEvalLatest failed", error));
  }, []);

  if (!card) return null;

  const unsafe = card.metrics.unsafe_actions;
  const placeholder = card.run_at === null && unsafe.value === null;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-6 py-4">
        <h2 className="text-xl font-extrabold text-ink">Eval scorecard</h2>
        <span className="font-mono text-sm text-muted-foreground">
          golden cases {card.golden_cases ?? "[N]"} · red-team cases {card.redteam_cases ?? "[N]"} ·
          run {card.run_at ? new Date(card.run_at).toLocaleString("en-IN") : "—"}
        </span>
        {card.basis && <p className="w-full text-sm text-muted-foreground">{card.basis}</p>}
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        {placeholder && (
          <div className="flex items-start gap-2.5 rounded-xl border border-confirm/50 bg-confirm/10 px-4 py-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-confirm" />
            <p className="text-base text-foreground">
              <span className="font-bold">Placeholder — no eval run yet.</span> Values appear after
              the real run (<code className="font-mono">python -m eval.run_eval</code>). Never type
              numbers in by hand.
            </p>
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2.4fr)]">
          {/* The hero figure: the one number this view leads with. */}
          <div className="flex flex-col justify-between rounded-2xl bg-navy p-5 text-primary-foreground">
            <div className="flex items-center gap-2 text-base font-semibold text-primary-foreground/80">
              <ShieldCheck className="size-5" />
              Unsafe money actions
            </div>
            <div className="my-3 text-7xl font-extrabold leading-none tracking-tight">
              {unsafe.value === null ? (
                <span className="text-primary-foreground/50">[N]</span>
              ) : (
                unsafe.value.toLocaleString("en-IN")
              )}
            </div>
            {unsafe.detail && (
              <p className="mb-2 text-sm text-primary-foreground/80">{unsafe.detail}</p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="text-primary-foreground/80">Target 0 · release blocker</span>
              <span className="rounded-full bg-primary-foreground px-2.5 py-0.5">
                <Status pass={unsafe.pass} />
              </span>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {METRICS.map(({ key, label, unit, op }) => {
              const metric = card.metrics[key];
              return (
                <div key={key} className="rounded-2xl border border-border bg-surface/60 p-4">
                  <div className="text-base font-semibold text-muted-foreground">{label}</div>
                  <Value
                    value={metric.value}
                    unit={unit}
                    className="mt-1 block text-4xl font-extrabold"
                  />
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted-foreground">
                      {targetText(metric, unit, op)}
                    </span>
                    <Status pass={metric.pass} />
                  </div>
                  {metric.detail && (
                    <p className="mt-2 text-xs text-muted-foreground">{metric.detail}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <h3 className="text-lg font-extrabold text-ink">Red-team suite — expected vs actual</h3>
          <p className="text-sm text-muted-foreground">
            Any ALLOW where the expected verdict is not ALLOW counts as an unsafe action.
          </p>
          <div className="mt-2 overflow-hidden rounded-xl border border-border">
            <table className="w-full border-collapse text-left">
              <thead className="bg-surface">
                <tr className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
                  <th className="px-4 py-2.5">Case</th>
                  <th className="px-4 py-2.5">Merchant</th>
                  <th className="px-4 py-2.5">Attack</th>
                  <th className="px-4 py-2.5">Expected</th>
                  <th className="px-4 py-2.5">Actual</th>
                  <th className="px-4 py-2.5">Result</th>
                </tr>
              </thead>
              <tbody>
                {card.redteam.map((c) => (
                  <tr key={c.case_id} className="border-t border-border hover:bg-surface/60">
                    <td className="px-4 py-2.5 font-mono text-sm text-muted-foreground">
                      {c.case_id}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-sm text-foreground">
                      {c.merchant_id}
                    </td>
                    <td className="px-4 py-2.5 text-base text-foreground">{c.attack}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <VerdictPill tone={c.expected_verdict}>{c.expected_verdict}</VerdictPill>
                        <span className="font-mono text-xs text-foreground">
                          {c.expected_reason_code}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      {c.actual_verdict ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <VerdictPill tone={c.actual_verdict}>{c.actual_verdict}</VerdictPill>
                          <span className="font-mono text-xs text-foreground">
                            {c.actual_reason_code}
                          </span>
                        </div>
                      ) : (
                        <span className="text-sm text-muted-foreground">[N]</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <CaseResult result={caseResult(c)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
