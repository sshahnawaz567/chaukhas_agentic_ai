import { BellRing, CheckCircle2 } from "lucide-react";

import type { ProactiveAlertData } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

/**
 * Chaukas speaks first: it noticed a failed settlement on its own. Deliberately
 * different from a normal reply (amber accent, glow on arrival, big amount), with
 * the merchant's yes/no inside the bubble. Nothing moves until "haan" — even under
 * the auto-limit — because the merchant did not ask (PROACTIVE_FEATURE_CHANGES §1).
 */
export function ProactiveAlertCard({
  alert,
  state,
  onConfirm,
}: {
  alert: ProactiveAlertData;
  state: "pending" | "consented" | "declined";
  onConfirm: (pendingAuditId: string, approve: boolean) => void;
}) {
  return (
    <div
      className={cn(
        "w-full rounded-2xl border border-l-4 border-confirm/40 border-l-confirm bg-card p-4 shadow-[var(--shadow-soft)]",
        state === "pending" && "alert-glow",
      )}
    >
      <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-navy">
        <BellRing className="size-4 text-confirm" />
        Chaukas ने देखा
      </div>

      <div className="mt-2 text-3xl font-extrabold tracking-tight text-ink">{alert.amount}</div>
      <p className="text-base font-semibold text-foreground">{alert.cause}</p>
      <p className="font-mono text-xs text-muted-foreground">{alert.settlementId}</p>

      <p className="mt-3 text-base leading-relaxed text-foreground">{alert.text}</p>

      {state === "pending" ? (
        <div className="mt-3 flex gap-2.5">
          <button
            type="button"
            onClick={() => onConfirm(alert.pendingAuditId, true)}
            className="flex-1 rounded-xl bg-navy px-4 py-2.5 text-base font-semibold text-primary-foreground transition-colors hover:bg-navy/90"
          >
            हाँ, ठीक करें
          </button>
          <button
            type="button"
            onClick={() => onConfirm(alert.pendingAuditId, false)}
            className="flex-1 rounded-xl border border-border bg-card px-4 py-2.5 text-base font-semibold text-foreground transition-colors hover:bg-accent"
          >
            अभी नहीं
          </button>
        </div>
      ) : state === "consented" ? (
        <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-allow/40 bg-allow/10 px-3 py-1 text-sm font-bold text-allow">
          <CheckCircle2 className="size-4" />
          हाँ — payment dobara bhej diya
        </div>
      ) : (
        <div className="mt-3 inline-flex rounded-full border border-border bg-muted px-3 py-1 text-sm font-semibold text-muted-foreground">
          Theek hai — jab chahein bata dijiye
        </div>
      )}
    </div>
  );
}
