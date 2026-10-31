import type { LoanOfferData } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

export function LoanOfferCard({
  offer,
  state,
  onConfirm,
}: {
  offer: LoanOfferData;
  state: "pending" | "consented" | "declined";
  onConfirm: (pendingAuditId: string, approve: boolean) => void;
}) {
  return (
    <div className="w-full max-w-md rounded-2xl border border-border bg-card p-4 shadow-[var(--shadow-soft)]">
      <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
        {offer.product === "credit_line" ? "Short-term credit line" : "Business loan"}
      </span>

      <h4 className="mt-1.5 text-lg font-bold leading-snug text-ink">{offer.title}</h4>
      <p className="mt-0.5 text-sm text-muted-foreground">{offer.sub}</p>

      <div className="mt-3 rounded-xl bg-surface p-3">
        <div className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Key Fact Statement
        </div>
        <dl className="mt-2 space-y-1.5">
          {offer.kfsRows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-muted-foreground">{row.label}</dt>
              <dd className="text-base font-semibold text-foreground">{row.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs italic text-muted-foreground">{offer.kfsNote}</p>
      </div>

      {state === "pending" ? (
        <div className="mt-3 flex gap-2.5">
          <button
            type="button"
            onClick={() => onConfirm(offer.pendingAuditId, true)}
            className="flex-1 rounded-xl bg-navy px-4 py-2.5 text-base font-semibold text-primary-foreground transition-colors hover:bg-navy/90"
          >
            हाँ, आगे बढ़ें
          </button>
          <button
            type="button"
            onClick={() => onConfirm(offer.pendingAuditId, false)}
            className="flex-1 rounded-xl border border-border bg-card px-4 py-2.5 text-base font-semibold text-foreground transition-colors hover:bg-accent"
          >
            अभी नहीं
          </button>
        </div>
      ) : (
        <div className="mt-3">
          <span
            className={cn(
              "inline-flex items-center rounded-full border px-3 py-1 text-sm font-bold",
              state === "consented"
                ? "border-allow/40 bg-allow/10 text-allow"
                : "border-border bg-muted text-muted-foreground",
            )}
          >
            {state === "consented" ? "Consent recorded" : "Declined"}
          </span>
        </div>
      )}
    </div>
  );
}
