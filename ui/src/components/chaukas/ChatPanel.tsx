import { useEffect, useRef, useState } from "react";
import {
  BatteryFull,
  CheckCheck,
  Lock,
  Mic,
  SendHorizontal,
  Settings,
  ShieldCheck,
  Signal,
  Store,
  UserRound,
  Wifi,
} from "lucide-react";

import type { ChatMessage, Merchant, PhoneNotice } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

import { SettlementCard } from "./SettlementCard";
import { LoanOfferCard } from "./LoanOfferCard";
import { PhoneLockScreen } from "./PhoneLockScreen";
import { ConsentSettings } from "./ConsentSettings";
import { InsuranceOfferCard } from "./InsuranceOfferCard";
import { ProactiveAlertCard } from "./ProactiveAlertCard";

/**
 * The merchant's view, drawn as a phone running the Paytm for Business app, so
 * the judges see exactly what a merchant would see. The trace panel next to it
 * is the "inside" view.
 */

/** Time the message appeared. Messages mount once, so this is their arrival time. */
function useArrivalTime() {
  const [time] = useState(() =>
    new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }),
  );
  return time;
}

function AiBadge() {
  return (
    <span className="inline-flex items-center rounded bg-cyan px-1 py-px text-[9px] font-extrabold uppercase tracking-widest text-ink">
      AI
    </span>
  );
}

function BotAvatar() {
  return (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-navy text-cyan">
      <ShieldCheck className="size-4" />
    </span>
  );
}

/** The DPDP notice, one tap away under the AI-disclosure line. */
function MoreDetails({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1.5 border-t border-border pt-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-sm font-semibold text-navy hover:underline"
      >
        <Lock className="size-3.5" />
        {open ? "छुपाएँ" : "आपकी जानकारी का उपयोग — पढ़ें"}
      </button>
      {open && (
        <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
          {text}
        </p>
      )}
    </div>
  );
}

function MessageItem({
  message,
  onConfirm,
}: {
  message: ChatMessage;
  onConfirm: (pendingAuditId: string, approve: boolean) => void;
}) {
  const time = useArrivalTime();

  if (message.role === "merchant") {
    return (
      <div className="bubble-in flex flex-col items-end">
        <div className="max-w-[85%] rounded-3xl rounded-br-md bg-cyan px-4 py-2.5 text-base leading-relaxed text-ink shadow-[var(--shadow-soft)]">
          {message.text}
        </div>
        <span className="mt-1 flex items-center gap-1 pr-1 text-[11px] text-muted-foreground">
          {time}
          <CheckCheck className="size-3.5 text-cyan" aria-label="Delivered" />
        </span>
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="bubble-in text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
          {message.text}
        </span>
      </div>
    );
  }

  let body: React.ReactNode = null;
  if (message.kind === "text") {
    body = (
      <div className="rounded-3xl rounded-bl-md border border-border bg-card px-4 py-2.5 text-base leading-relaxed text-foreground shadow-[var(--shadow-soft)]">
        {message.text}
        {message.details && <MoreDetails text={message.details} />}
      </div>
    );
  } else if (message.kind === "settlement-card" && message.settlement) {
    body = <SettlementCard settlement={message.settlement} />;
  } else if (message.kind === "proactive-alert" && message.alert) {
    body = (
      <ProactiveAlertCard
        alert={message.alert}
        state={message.alertState ?? "pending"}
        onConfirm={onConfirm}
      />
    );
  } else if (message.kind === "insurance-offer" && message.insurance) {
    body = (
      <InsuranceOfferCard
        offer={message.insurance}
        state={message.insuranceState ?? "pending"}
        insuranceRef={message.insuranceRef}
        onConfirm={onConfirm}
      />
    );
  } else if (message.kind === "loan-offer" && message.offer) {
    body = (
      <LoanOfferCard
        offer={message.offer}
        state={message.offerState ?? "pending"}
        onConfirm={onConfirm}
      />
    );
  }
  if (!body) return null;

  // Every bot message carries the AI badge (RBI FREE-AI: disclose that it is an AI).
  return (
    <div className="bubble-in flex items-end gap-2">
      <BotAvatar />
      <div className={cn("min-w-0", message.kind === "text" ? "max-w-[85%]" : "flex-1 pr-2")}>
        {body}
        <span className="mt-1 flex items-center gap-1.5 pl-1 text-[11px] text-muted-foreground">
          <AiBadge />
          {time}
        </span>
      </div>
    </div>
  );
}

export function ChatPanel({
  merchant,
  messages,
  quickReplies,
  busy,
  onSend,
  onHuman,
  onConfirm,
  notice = null,
  sessionId,
  onOpenNotice,
}: {
  merchant: Merchant | null;
  messages: ChatMessage[];
  quickReplies: string[];
  busy: boolean;
  onSend: (text: string) => void;
  onHuman: () => void;
  onConfirm: (pendingAuditId: string, approve: boolean) => void;
  /** Proactive flow: a push notification is waiting on the lock screen; tapping it opens the chat. */
  notice?: PhoneNotice | null;
  onOpenNotice?: () => void;
  sessionId?: string | undefined;
}) {
  const scrollRef = useChatAutoScroll(messages.length);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="flex h-full items-center justify-center">
      {/* Device bezel */}
      <div className="flex h-full max-h-[880px] w-full max-w-[410px] flex-col rounded-[2.75rem] bg-ink p-2.5 shadow-[0_24px_60px_-20px_rgba(0,41,112,0.55)]">
        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[2.25rem] bg-surface">
          {settingsOpen && merchant && (
            <ConsentSettings
              merchantId={merchant.id}
              sessionId={sessionId}
              onClose={() => setSettingsOpen(false)}
            />
          )}
          {/* Notch */}
          <span
            aria-hidden
            className="absolute left-1/2 top-2 z-10 h-5 w-24 -translate-x-1/2 rounded-full bg-ink"
          />

          {notice ? (
            <PhoneLockScreen notice={notice} onOpen={() => onOpenNotice?.()} />
          ) : (
            <>
              {/* Status bar + app header */}
              <div className="shrink-0 bg-navy text-primary-foreground">
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
                <div className="flex items-center gap-3 px-4 pb-3 pt-2">
                  <span className="flex size-10 items-center justify-center rounded-full bg-primary-foreground/10 text-cyan">
                    <ShieldCheck className="size-5" />
                  </span>
                  <div className="min-w-0">
                    <div className="text-base font-bold leading-tight">Chaukas</div>
                    <div className="truncate text-xs text-cyan">online · आपका AI teammate</div>
                  </div>
                  <span className="ml-auto shrink-0 rounded-full bg-primary-foreground/10 px-3 py-1 text-[11px] font-semibold text-primary-foreground/90">
                    Paytm for Business
                  </span>
                  <button
                    type="button"
                    onClick={() => setSettingsOpen(true)}
                    disabled={!merchant}
                    aria-label="Chat settings and consents"
                    className="flex size-8 shrink-0 items-center justify-center rounded-full text-primary-foreground/90 hover:bg-primary-foreground/10 disabled:opacity-40"
                  >
                    <Settings className="size-4" />
                  </button>
                </div>
              </div>

              {/* Who is chatting (demo context for the judges) */}
              <div className="flex shrink-0 items-center gap-2 border-b border-border bg-accent px-4 py-1.5 text-xs text-navy">
                <Store className="size-3.5 shrink-0" />
                {merchant ? (
                  <span className="truncate">
                    <span className="font-bold">{merchant.name}</span> · {merchant.id}
                    {merchant.demoNote ? ` · ${merchant.demoNote}` : ""}
                  </span>
                ) : (
                  <span>Upar se merchant chuniye</span>
                )}
              </div>

              {/* Messages */}
              <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-4">
                {messages.map((message) => (
                  <MessageItem key={message.id} message={message} onConfirm={onConfirm} />
                ))}
              </div>

              {/* Quick replies + composer */}
              <div className="shrink-0 space-y-2 border-t border-border bg-surface px-3 pb-1.5 pt-2.5">
                <div className="flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    onClick={onHuman}
                    disabled={busy}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border border-border bg-card px-3 py-1.5 text-sm font-medium text-navy transition-colors hover:bg-accent",
                      busy && "pointer-events-none opacity-50",
                    )}
                  >
                    <UserRound className="size-3.5" />
                    इंसान से बात करें
                  </button>
                  {quickReplies.map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      disabled={busy}
                      onClick={() => onSend(chip)}
                      title={chip}
                      className={cn(
                        "max-w-full truncate rounded-full border border-cyan/50 bg-accent px-3 py-1.5 text-sm font-medium text-navy",
                        "transition-colors hover:bg-cyan hover:text-ink",
                        busy && "pointer-events-none opacity-50",
                      )}
                    >
                      {chip}
                    </button>
                  ))}
                </div>

                <form
                  className="flex items-center gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const input = event.currentTarget.elements.namedItem(
                      "chat-input",
                    ) as HTMLInputElement;
                    const text = input.value;
                    if (!text.trim() || busy) return;
                    input.value = "";
                    onSend(text);
                  }}
                >
                  <div className="flex min-w-0 flex-1 items-center rounded-full border border-input bg-card py-1 pl-4 pr-1 shadow-[var(--shadow-soft)] focus-within:ring-2 focus-within:ring-ring">
                    <input
                      name="chat-input"
                      placeholder="Message लिखें…"
                      autoComplete="off"
                      className="min-w-0 flex-1 bg-transparent py-1.5 text-base outline-none placeholder:text-muted-foreground"
                    />
                    <button
                      type="submit"
                      aria-label="Send message"
                      disabled={busy}
                      className="flex size-9 shrink-0 items-center justify-center rounded-full bg-navy text-primary-foreground transition-colors hover:bg-navy/90 disabled:opacity-50"
                    >
                      <SendHorizontal className="size-4" />
                    </button>
                  </div>
                  <div className="group relative">
                    <button
                      type="button"
                      aria-label="Voice input (voice coming soon)"
                      disabled={busy}
                      className="flex size-11 items-center justify-center rounded-full bg-cyan text-ink shadow-[var(--shadow-soft)] transition-colors hover:bg-cyan/90 disabled:opacity-50"
                    >
                      <Mic className="size-5" />
                    </button>
                    <div className="pointer-events-none absolute bottom-full right-0 mb-1.5 whitespace-nowrap rounded-lg bg-ink px-2.5 py-1 text-xs font-medium text-primary-foreground opacity-0 transition-opacity group-hover:opacity-100">
                      Voice coming soon
                    </div>
                  </div>
                </form>

                {/* Home indicator */}
                <div aria-hidden className="flex justify-center pt-1">
                  <span className="h-1 w-28 rounded-full bg-ink/25" />
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function useChatAutoScroll(dep: number) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [dep]);
  return ref;
}
