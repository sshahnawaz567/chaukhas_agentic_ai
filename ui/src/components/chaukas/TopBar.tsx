import { Zap } from "lucide-react";

import type { AppView, Merchant } from "@/lib/chaukas-types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

const VIEWS: { mode: AppView; label: string }[] = [
  { mode: "merchant", label: "Merchant" },
  { mode: "agent", label: "Agent desk" },
  { mode: "redteam", label: "Red team" },
  { mode: "audit", label: "Audit" },
  { mode: "scorecard", label: "Scorecard" },
];

export function TopBar({
  merchants,
  selectedId,
  onSelect,
  view,
  onView,
  onSimulate,
  simulateDisabled = false,
}: {
  merchants: Merchant[];
  selectedId: string | null;
  onSelect: (merchantId: string) => void;
  view: AppView;
  onView: (view: AppView) => void;
  /** Proactive demo trigger. Lives outside the phone: it stands for the system, not the merchant. */
  onSimulate?: (() => void) | undefined;
  simulateDisabled?: boolean;
}) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-5 bg-navy px-5 text-primary-foreground">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-full bg-cyan text-xl font-extrabold text-navy">
          च
        </div>
        <div>
          <div className="text-lg font-extrabold leading-tight">Chaukas</div>
          <div className="text-xs text-primary-foreground/70">AI teammate for Paytm merchants</div>
        </div>
      </div>

      <div className="w-72">
        <Select value={selectedId ?? ""} onValueChange={onSelect}>
          <SelectTrigger className="w-full border-primary-foreground/25 bg-primary-foreground/10 text-primary-foreground data-[placeholder]:text-primary-foreground/60">
            <SelectValue placeholder="Choose a merchant…" />
          </SelectTrigger>
          <SelectContent>
            {merchants.map((merchant) => (
              <SelectItem key={merchant.id} value={merchant.id}>
                {merchant.id} · {merchant.name} · {merchant.demoNote}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {onSimulate && (
        <button
          type="button"
          onClick={onSimulate}
          disabled={simulateDisabled}
          title="Presenter control: the event watcher finds this merchant's failed settlement and Chaukas messages first"
          className="inline-flex items-center gap-1.5 rounded-full border border-confirm/60 bg-confirm/15 px-3.5 py-1.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-confirm/30 disabled:opacity-40"
        >
          <Zap className="size-4 text-confirm" />
          Simulate: settlement failed
        </button>
      )}

      <div className="ml-auto flex items-center rounded-full bg-primary-foreground/10 p-1">
        {VIEWS.map(({ mode, label }) => (
          <button
            key={mode}
            type="button"
            onClick={() => onView(mode)}
            className={cn(
              "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
              view === mode
                ? "bg-cyan text-primary-foreground"
                : "text-primary-foreground/75 hover:text-primary-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </header>
  );
}
