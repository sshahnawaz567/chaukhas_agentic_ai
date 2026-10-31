import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { getConsents, setConsent } from "@/api/client";
import { Switch } from "@/components/ui/switch";
import type { ConsentPurpose, ConsentView } from "@/lib/chaukas-types";

/**
 * Chat settings inside the phone: the merchant's consents (DPDP s.6 — withdrawing
 * is as easy as granting). Withdrawing "Insurance offers" stops future insurance
 * offers (the guardrail BLOCKs them with CONSENT_WITHDRAWN).
 */
const ROWS: { purpose: ConsentPurpose; label: string; hint: string; grantable: boolean }[] = [
  {
    purpose: "ai_assistance",
    label: "AI assistant",
    hint: "Chaukas aapki payment/support problem suljhaye",
    grantable: true,
  },
  {
    purpose: "loan_offer",
    label: "Loan offers",
    hint: "Haan sirf offer card pe KFS padhne ke baad di ja sakti hai",
    grantable: false,
  },
  {
    purpose: "insurance_offer",
    label: "Insurance offers",
    hint: "Band karne pe aage koi insurance offer nahi aayega",
    grantable: true,
  },
];

export function ConsentSettings({
  merchantId,
  sessionId,
  onClose,
}: {
  merchantId: string;
  sessionId?: string | undefined;
  onClose: () => void;
}) {
  const [view, setView] = useState<ConsentView | null>(null);
  const [saving, setSaving] = useState<ConsentPurpose | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getConsents(merchantId)
      .then(setView)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [merchantId]);

  const toggle = async (purpose: ConsentPurpose, on: boolean) => {
    setSaving(purpose);
    setError(null);
    try {
      setView(await setConsent(merchantId, purpose, on ? "granted" : "withdrawn", sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-surface">
      <div className="flex shrink-0 items-center gap-2 bg-navy px-4 pb-3 pt-9 text-primary-foreground">
        <h3 className="text-base font-bold">Chat settings · Consents</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close settings"
          className="ml-auto flex size-9 items-center justify-center rounded-full hover:bg-primary-foreground/10"
        >
          <X className="size-5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        <p className="px-1 text-sm text-muted-foreground">
          {merchantId} · aap kabhi bhi apni ijaazat de ya wapas le sakte hain.
        </p>
        {ROWS.map(({ purpose, label, hint, grantable }) => {
          const on = view?.purposes[purpose]?.state === "granted";
          const disabled = !view || saving !== null || (!on && !grantable);
          return (
            <label
              key={purpose}
              className="flex items-center gap-3 rounded-xl border border-border bg-card p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="text-base font-semibold text-ink">{label}</div>
                <div className="text-sm text-muted-foreground">{hint}</div>
                <div className="text-xs text-muted-foreground">
                  {view?.purposes[purpose]?.state ?? "not asked yet"}
                </div>
              </div>
              <Switch
                checked={on}
                disabled={disabled}
                onCheckedChange={(checked) => void toggle(purpose, checked)}
                aria-label={label}
              />
            </label>
          );
        })}
        {error && (
          <p className="rounded-xl border border-block/40 bg-block/10 p-3 text-sm text-foreground">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
