import {
  BellRing,
  Crosshair,
  Database,
  MessageSquare,
  PhoneForwarded,
  Route,
  ShieldCheck,
  Zap,
} from "lucide-react";

import type { TraceAgent, TraceStep, TraceTurn, Verdict } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

import { VerdictPill, verdictBorderClasses } from "./VerdictPill";

const agentIcons: Record<TraceAgent, React.ComponentType<{ className?: string }>> = {
  Watcher: BellRing,
  Intent: Crosshair,
  Context: Database,
  Plan: Route,
  Guardrail: ShieldCheck,
  Action: Zap,
  Reply: MessageSquare,
  Handoff: PhoneForwarded,
};

function Meta({ step, className }: { step: TraceStep; className?: string }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center gap-2 font-mono text-xs text-muted-foreground",
        className,
      )}
    >
      <span>{step.latencyMs} ms</span>
      <span>{step.cost}</span>
    </span>
  );
}

function TraceRowItem({ step }: { step: TraceStep }) {
  const Icon = agentIcons[step.agent] ?? ShieldCheck;

  if (step.big && step.verdict && step.reason) {
    return (
      <div
        className={cn(
          "trace-in rounded-2xl border-l-4 p-3.5 shadow-[var(--shadow-soft)]",
          verdictBorderClasses[step.verdict as Verdict],
        )}
      >
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-card text-navy">
            <Icon className="size-4" />
          </span>
          <span className="text-sm font-bold uppercase tracking-wide text-foreground">
            {step.agent}
          </span>
          <VerdictPill tone={step.verdict as Verdict}>{step.verdict}</VerdictPill>
          <Meta step={step} className="ml-auto" />
        </div>
        <div className="mt-2 pl-[42px] text-lg font-extrabold leading-snug text-ink">
          {step.reason}
        </div>
        <div className="mt-0.5 pl-[42px] text-sm text-muted-foreground">{step.output}</div>
      </div>
    );
  }

  return (
    <div className="trace-in flex items-start gap-3 rounded-xl p-2.5 transition-colors hover:bg-surface">
      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface text-navy">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2.5">
          <span className="text-base font-bold text-foreground">{step.agent}</span>
          <Meta step={step} />
        </div>
        <p className="mt-0.5 break-words text-base leading-snug text-muted-foreground">
          {step.output}
        </p>
      </div>
    </div>
  );
}

export function TracePanel({
  traceId,
  turns,
  activeTurn,
  onSelectTurn,
}: {
  traceId: string | null;
  turns: TraceTurn[];
  activeTurn: number;
  onSelectTurn: (index: number) => void;
}) {
  const rows = turns[activeTurn]?.rows ?? [];
  const viewable = turns
    .map((turn, index) => ({ turn, index }))
    .filter(({ turn }) => turn.rows.length > 0);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
        <div>
          <h2 className="text-lg font-extrabold text-ink">Execution trace</h2>
          <div className="font-mono text-xs text-muted-foreground">
            {traceId ? `trace ${traceId}` : "trace —"}
          </div>
        </div>
        <div className="flex gap-1.5">
          {viewable.length === 0 && (
            <span className="rounded-full bg-muted px-3 py-1 text-sm text-muted-foreground">
              No turns yet
            </span>
          )}
          {viewable.map(({ turn, index }) => (
            <button
              key={index}
              type="button"
              onClick={() => onSelectTurn(index)}
              className={cn(
                "rounded-full px-3.5 py-1.5 text-sm font-semibold transition-colors",
                index === activeTurn
                  ? "bg-navy text-primary-foreground"
                  : "bg-surface text-navy hover:bg-accent",
              )}
            >
              {turn.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-4">
        {rows.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-1.5 text-center">
            <ShieldCheck className="size-9 text-muted-foreground/50" />
            <p className="text-base font-semibold text-foreground">No steps yet</p>
            <p className="text-sm text-muted-foreground">
              Every step Chaukas takes will appear here, with its verdict.
            </p>
          </div>
        ) : (
          rows.map((step) => <TraceRowItem key={step.id} step={step} />)
        )}
      </div>
    </div>
  );
}
