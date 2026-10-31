import { CheckCircle2, ShieldPlus } from "lucide-react";

import type { InsuranceOfferData } from "@/lib/chaukas-types";

/**
 * Shop insurance offer (simulated insurer). Deliberately unlike the loan KFS card:
 * calm teal accent and a shield. Figures are illustrative, the insurer is named,
 * and a "yes" only records interest — no premium, no policy (aligned with IRDAI
 * norms on disclosure; never "approved" or "certified").
 */

const REASON_LABEL: Record<string, string> = {
  CATEGORY_ELECTRONICS: "Electronics shop",
  PHYSICAL_SHOP: "You run a shop",
  DEVICE_TICKET_HISTORY: "Past device problem",
  HAS_DEVICE: "Paytm device",
  GMV_OK: "Sales fit",
};

const inr = (amount: number) => `₹${amount.toLocaleString("en-IN")}`;

export function InsuranceOfferCard({
  offer,
  state,
  insuranceRef,
  onConfirm,
}: {
  offer: InsuranceOfferData;
  state: "pending" | "consented" | "declined";
  insuranceRef?: string | undefined;
  onConfirm: (pendingAuditId: string, approve: boolean) => void;
}) {
  if (state === "consented") {
    return (
      <div className="w-full rounded-2xl border border-l-4 border-teal-600/40 border-l-teal-600 bg-card p-4 shadow-[var(--shadow-soft)]">
        <div className="flex items-center gap-2 text-base font-bold text-ink">
          <CheckCircle2 className="size-5 text-allow" />
          Interest noted{insuranceRef ? ` · Ref ${insuranceRef}` : ""}
        </div>
        <p className="mt-1 text-sm font-semibold text-foreground">{offer.product_name}</p>
        <p className="mt-1.5 text-base text-foreground">
          No premium charged. No policy issued yet. {offer.insurer_name} will contact you.
        </p>
      </div>
    );
  }

  if (state === "declined") {
    return (
      <div className="w-full rounded-2xl border border-border bg-muted/60 p-4">
        <p className="text-base font-semibold text-muted-foreground">
          Theek hai — kuch record nahi kiya
        </p>
        <p className="text-sm text-muted-foreground">{offer.product_name}</p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-2xl border border-l-4 border-teal-600/40 border-l-teal-600 bg-card p-4 shadow-[var(--shadow-soft)]">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-teal-700">
          <ShieldPlus className="size-4" />
          Shop insurance
        </span>
        <span className="rounded-full border border-teal-600/40 bg-teal-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-teal-800">
          Illustrative · sample figures
        </span>
      </div>

      <h4 className="mt-1.5 text-lg font-bold leading-snug text-ink">{offer.product_name}</h4>
      <p className="text-sm text-muted-foreground">by {offer.insurer_name}</p>

      <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-teal-50 p-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-teal-800">
            Cover up to
          </div>
          <div className="text-xl font-extrabold tabular-nums text-ink">{inr(offer.cover_inr)}</div>
        </div>
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-teal-800">
            Premium about
          </div>
          <div className="text-xl font-extrabold tabular-nums text-ink">
            {inr(offer.premium_inr)}
            <span className="text-sm font-semibold text-muted-foreground"> / year</span>
          </div>
        </div>
      </div>

      {offer.covers.length > 0 && (
        <ul className="mt-3 space-y-1">
          {offer.covers.map((c) => (
            <li key={c} className="flex items-start gap-2 text-base text-foreground">
              <CheckCircle2 className="mt-1 size-4 shrink-0 text-teal-600" />
              {c}
            </li>
          ))}
        </ul>
      )}

      {offer.reasons.length > 0 && (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Why this fits you
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {offer.reasons.map((r) => (
              <span
                key={r}
                className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-sm font-medium text-navy"
              >
                {REASON_LABEL[r] ?? r}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-col gap-2">
        <button
          type="button"
          onClick={() => onConfirm(offer.pendingAuditId, true)}
          className="rounded-xl bg-teal-700 px-4 py-2.5 text-base font-semibold text-primary-foreground transition-colors hover:bg-teal-800"
        >
          Haan, insurer mujhse baat kare
        </button>
        <button
          type="button"
          onClick={() => onConfirm(offer.pendingAuditId, false)}
          className="rounded-xl border border-border bg-card px-4 py-2.5 text-base font-semibold text-foreground transition-colors hover:bg-accent"
        >
          Abhi nahi
        </button>
      </div>

      <p className="mt-2 text-xs text-muted-foreground">
        Grievance: {offer.grievance_contact} · No premium is charged by saying yes.
      </p>
    </div>
  );
}
