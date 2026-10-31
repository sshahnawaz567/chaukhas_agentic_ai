import { BatteryFull, Hand, Signal, Wifi } from "lucide-react";

import type { PhoneNotice } from "@/lib/chaukas-types";

/**
 * What the merchant's phone shows when Chaukas reaches out first: the lock
 * screen with a push notification from the Paytm for Business app. Tapping it
 * opens the chat (the "app") on the notification bubble.
 */
export function PhoneLockScreen({ notice, onOpen }: { notice: PhoneNotice; onOpen: () => void }) {
  const today = new Date().toLocaleDateString("hi-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-[radial-gradient(120%_80%_at_20%_0%,#00BAF2_0%,#002970_55%,#00163d_100%)] text-primary-foreground">
      {/* Status bar */}
      <div
        aria-hidden
        className="flex items-center justify-between px-7 pb-1 pt-2.5 text-xs font-semibold"
      >
        <span>9:41</span>
        <span className="flex items-center gap-1">
          <Signal className="size-3.5" />
          <Wifi className="size-3.5" />
          <BatteryFull className="size-4" />
        </span>
      </div>

      {/* Clock */}
      <div className="mt-8 text-center">
        <div className="text-sm font-medium text-primary-foreground/80">{today}</div>
        <div className="text-7xl font-bold leading-none tracking-tight">9:41</div>
      </div>

      {/* Push notification */}
      <div className="mt-8 px-3">
        <button
          type="button"
          onClick={onOpen}
          className="notif-in w-full rounded-3xl bg-card/95 p-3.5 text-left text-foreground shadow-[0_18px_40px_-12px_rgba(0,0,0,0.55)] backdrop-blur transition-transform hover:scale-[1.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan"
          aria-label={`Open notification: ${notice.title}`}
        >
          <div className="flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-md bg-navy text-xs font-extrabold text-cyan">
              च
            </span>
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Paytm for Business
            </span>
            <span className="ml-auto text-xs text-muted-foreground">अभी</span>
          </div>
          <div className="mt-2 text-base font-bold leading-snug text-ink">{notice.title}</div>
          <p className="mt-0.5 line-clamp-3 text-sm leading-snug text-foreground">{notice.body}</p>
        </button>
      </div>

      {/* Presenter hint */}
      <div className="mt-auto flex flex-col items-center gap-2 pb-3">
        <span className="inline-flex animate-pulse items-center gap-1.5 rounded-full bg-primary-foreground/15 px-3 py-1 text-xs font-semibold">
          <Hand className="size-3.5" />
          Notification पर tap करें
        </span>
        <span aria-hidden className="h-1 w-28 rounded-full bg-primary-foreground/60" />
      </div>
    </div>
  );
}
