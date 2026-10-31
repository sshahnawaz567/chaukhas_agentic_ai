import type { SettlementCardData } from "@/lib/chaukas-types";

import { VerdictPill } from "./VerdictPill";

export function SettlementCard({ settlement }: { settlement: SettlementCardData }) {
  return (
    <div className="w-full max-w-md rounded-2xl border border-border bg-card p-4 shadow-[var(--shadow-soft)]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Settlement
        </span>
        <span className="font-mono text-xs text-muted-foreground">{settlement.id}</span>
      </div>

      <div className="mt-1.5 flex items-baseline gap-2.5">
        <span className="text-2xl font-extrabold tracking-tight text-ink">{settlement.amount}</span>
        <span className="text-sm text-muted-foreground">{settlement.age}</span>
      </div>

      <p className="mt-2 text-base leading-snug text-foreground">{settlement.failure}</p>
      {settlement.note && <p className="mt-0.5 text-sm text-muted-foreground">{settlement.note}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <VerdictPill tone={settlement.statusTone}>{settlement.statusPill}</VerdictPill>
        {settlement.ticket && (
          <span className="rounded-full border border-border bg-muted px-3 py-1 text-sm font-medium text-foreground">
            {settlement.ticket}
          </span>
        )}
      </div>

      {settlement.guardrailNote && (
        <div className="mt-3 border-t border-border pt-2.5">
          <VerdictPill tone="ALLOW" className="bg-allow/10 text-allow">
            {settlement.guardrailNote}
          </VerdictPill>
        </div>
      )}
    </div>
  );
}
