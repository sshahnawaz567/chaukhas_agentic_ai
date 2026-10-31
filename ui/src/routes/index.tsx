import { useEffect, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";

import {
  USE_MOCK,
  confirm,
  createSession,
  getMerchants,
  sendMessage,
  simulateEvent,
} from "@/api/client";
import { TopBar } from "@/components/chaukas/TopBar";
import { ChatPanel } from "@/components/chaukas/ChatPanel";
import { TracePanel } from "@/components/chaukas/TracePanel";
import { AgentDesk } from "@/components/chaukas/AgentDesk";
import { RedTeamPanel } from "@/components/chaukas/RedTeamPanel";
import { AuditPanel } from "@/components/chaukas/AuditPanel";
import { ScorecardPanel } from "@/components/chaukas/ScorecardPanel";
import type {
  AppView,
  BotElement,
  ChatMessage,
  Merchant,
  PhoneNotice,
  ProactiveStart,
  Session,
  TraceRow,
  TraceTurn,
} from "@/lib/chaukas-types";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Chaukas — AI teammate for Paytm merchants" },
      {
        name: "description",
        content:
          "Chaukas watches every merchant conversation, verifies actions against policy and shows its full execution trace.",
      },
      { property: "og:title", content: "Chaukas — AI teammate for Paytm merchants" },
      {
        property: "og:description",
        content:
          "Chaukas watches every merchant conversation, verifies actions against policy and shows its full execution trace.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

let messageSeq = 0;
const nextMessageId = () => `msg-${++messageSeq}`;
let rowSeq = 0;
const nextRowId = () => `row-${++rowSeq}`;

/**
 * The session greeting is the AI-disclosure line, a blank line, then the DPDP
 * notice. Show the one line; keep the full notice one tap away (layered notice).
 * The backend wording is untouched, so its notice_version still matches.
 */
function greetingMessage(text: string): ChatMessage {
  const cut = text.indexOf("\n\n");
  const message: ChatMessage = {
    id: nextMessageId(),
    role: "bot",
    kind: "text",
    text: text.trim(),
  };
  if (cut > 0) {
    message.text = text.slice(0, cut).trim();
    message.details = text.slice(cut).trim();
  }
  return message;
}

function toMessage(element: BotElement): ChatMessage {
  const message: ChatMessage = {
    id: nextMessageId(),
    role: "bot",
    kind: element.type,
    text: element.text ?? "",
  };
  if (element.settlement) message.settlement = element.settlement;
  if (element.offer) {
    message.offer = element.offer;
    message.offerState = "pending";
  }
  if (element.alert) {
    message.alert = element.alert;
    message.alertState = "pending";
  }
  if (element.insurance) {
    message.insurance = element.insurance;
    message.insuranceState = "pending";
  }
  return message;
}

function Index() {
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState<AppView>("merchant");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [quickReplies, setQuickReplies] = useState<string[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [traceTurns, setTraceTurns] = useState<TraceTurn[]>([]);
  const [activeTraceTurn, setActiveTraceTurn] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<PhoneNotice | null>(null);
  const noticeRef = useRef<ProactiveStart | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    getMerchants()
      .then(setMerchants)
      .catch((error) => console.error("getMerchants failed", error));
  }, []);

  const selectedMerchant = merchants.find((m) => m.id === selectedId) ?? null;

  const selectMerchant = async (merchantId: string) => {
    setSelectedId(merchantId);
    setNotice(null);
    noticeRef.current = null;
    let newSession: Session;
    try {
      newSession = await createSession(merchantId);
    } catch (error) {
      console.error("createSession failed", error);
      setSession(null);
      setMessages([]);
      showError(error);
      return;
    }
    setSession(newSession);
    setMessages([greetingMessage(newSession.greetingText)]);
    setQuickReplies(newSession.quickReplies);
    setTraceId(null);
    setTraceTurns([{ label: "Session", rows: [], streaming: false }]);
    setActiveTraceTurn(0);
  };

  const appendRowToLastTurn = async (row: TraceRow) => {
    await sleep(300);
    const step = { ...row, id: nextRowId() };
    setTraceTurns((prev) => {
      const last = prev[prev.length - 1];
      if (!last) return prev;
      const copy = [...prev];
      copy[copy.length - 1] = {
        label: last.label,
        rows: [...last.rows, step],
        streaming: last.streaming,
      };
      return copy;
    });
  };

  const streamTurn = async (trace: TraceRow[]) => {
    setTraceTurns((prev) => {
      setActiveTraceTurn(prev.length);
      return [...prev, { label: `Turn ${prev.length}`, rows: [], streaming: true }];
    });
    for (const row of trace) {
      await appendRowToLastTurn(row);
    }
    setTraceTurns((prev) => {
      const last = prev[prev.length - 1];
      if (!last) return prev;
      const copy = [...prev];
      copy[copy.length - 1] = { label: last.label, rows: last.rows, streaming: false };
      return copy;
    });
  };

  const handleSend = async (text: string) => {
    if (!session || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setMessages((prev) => [...prev, { id: nextMessageId(), role: "merchant", kind: "text", text }]);
    try {
      const result = await sendMessage(session.id, text);
      setTraceId(result.traceId);
      for (const element of result.bot) {
        await sleep(350);
        setMessages((prev) => [...prev, toMessage(element)]);
      }
      await streamTurn(result.trace);
    } catch (error) {
      console.error("sendMessage failed", error);
      showError(error);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const handleConfirm = async (pendingAuditId: string, approve: boolean) => {
    if (!session || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const result = await confirm(session.id, pendingAuditId, approve);
      setMessages((prev) =>
        prev.map((message) =>
          message.offer?.pendingAuditId === pendingAuditId
            ? { ...message, offerState: result.offerState }
            : message.alert?.pendingAuditId === pendingAuditId
              ? { ...message, alertState: result.offerState }
              : message.insurance?.pendingAuditId === pendingAuditId
                ? {
                    ...message,
                    insuranceState: result.offerState,
                    ...(result.insuranceRef ? { insuranceRef: result.insuranceRef } : {}),
                  }
                : message,
        ),
      );
      await sleep(250);
      if (result.bot) {
        // Real API: the confirm turn can bring cards and a second offer (proactive flow).
        for (const element of result.bot) {
          await sleep(350);
          setMessages((prev) => [...prev, toMessage(element)]);
        }
      } else {
        setMessages((prev) => [
          ...prev,
          { id: nextMessageId(), role: "bot", kind: "text", text: result.botText },
        ]);
      }
      if (result.handoffNote && !result.bot) {
        const note = result.handoffNote;
        setMessages((prev) => [
          ...prev,
          { id: nextMessageId(), role: "system", kind: "system-line", text: note },
        ]);
      }
      for (const row of result.trace) await appendRowToLastTurn(row);
    } catch (error) {
      console.error("confirm failed", error);
      showError(error);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  /**
   * Presenter-side "⚡ Simulate: settlement failed": the backend's event watcher
   * opens a new session and Chaukas speaks first. Nobody types anything.
   */
  const handleSimulate = async () => {
    if (!selectedId || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setView("merchant");
    try {
      const started = await simulateEvent(selectedId);
      const alert = started.result.bot.find((b) => b.alert)?.alert;
      // The phone goes to its lock screen and the push notification slides in.
      setSession(null);
      setMessages([]);
      setQuickReplies([]);
      setNotice({
        title: alert
          ? `${alert.amount} का settlement fail हुआ`
          : "Chaukas ने आपके account में कुछ देखा",
        body: alert?.text ?? started.result.bot.find((b) => b.text)?.text ?? "",
      });
      noticeRef.current = started;
      // Meanwhile the trace shows what Chaukas did on its own to get here.
      setTraceId(started.result.traceId);
      setTraceTurns([{ label: "Session", rows: [], streaming: false }]);
      setActiveTraceTurn(0);
      await streamTurn(started.result.trace);
    } catch (error) {
      console.error("simulateEvent failed", error);
      const detail = error instanceof Error ? error.message : String(error);
      setMessages((prev) => [
        ...prev,
        { id: nextMessageId(), role: "system", kind: "system-line", text: detail },
      ]);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  /** The merchant taps the notification: the app opens on Chaukas's message. */
  const handleOpenNotice = async () => {
    // Not behind the busy lock: the trace may still be streaming when the presenter taps.
    const started = noticeRef.current;
    if (!started) return;
    noticeRef.current = null;
    setNotice(null);
    setSession(started.session);
    setQuickReplies(started.session.quickReplies);
    setMessages(
      started.session.greetingText ? [greetingMessage(started.session.greetingText)] : [],
    );
    for (const element of started.result.bot) {
      await sleep(450);
      setMessages((prev) => [...prev, toMessage(element)]);
    }
  };

  /** A failed call shows up in the chat, so nobody on stage waits for a reply that never comes. */
  const showError = (error: unknown) => {
    const detail = error instanceof Error ? error.message : String(error);
    setMessages((prev) => [
      ...prev,
      {
        id: nextMessageId(),
        role: "system",
        kind: "system-line",
        text: `Could not reach Chaukas (${detail}). Is the API running on port 8000?`,
      },
    ]);
  };

  const handleHuman = () => {
    // Real mode: asking for a human is a merchant message like any other — the
    // backend classifies it as human_request and always hands off (with a brief).
    if (!USE_MOCK) {
      void handleSend("मुझे किसी इंसान से बात करनी है।");
      return;
    }
    setMessages((prev) => [
      ...prev,
      {
        id: nextMessageId(),
        role: "system",
        kind: "system-line",
        text: "Request noted · a Paytm teammate will respond",
      },
    ]);
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <TopBar
        merchants={merchants}
        selectedId={selectedId}
        onSelect={selectMerchant}
        view={view}
        onView={setView}
        onSimulate={USE_MOCK ? undefined : handleSimulate}
        simulateDisabled={!selectedId || busy}
      />

      {view === "agent" ? (
        <main className="min-h-0 flex-1 p-4">
          <AgentDesk />
        </main>
      ) : view === "redteam" ? (
        <main className="min-h-0 flex-1 p-4">
          <RedTeamPanel />
        </main>
      ) : view === "audit" ? (
        <main className="min-h-0 flex-1 p-4">
          <AuditPanel />
        </main>
      ) : view === "scorecard" ? (
        <main className="min-h-0 flex-1 p-4">
          <ScorecardPanel />
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 gap-4 p-4">
          <section className="min-h-0 w-1/2 rounded-2xl border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            <ChatPanel
              merchant={selectedMerchant}
              messages={messages}
              quickReplies={quickReplies}
              busy={busy}
              onSend={handleSend}
              onHuman={handleHuman}
              onConfirm={handleConfirm}
              notice={notice}
              sessionId={session?.id}
              onOpenNotice={handleOpenNotice}
            />
          </section>
          <section className="min-h-0 w-1/2 min-w-0">
            <TracePanel
              traceId={traceId}
              turns={traceTurns}
              activeTurn={activeTraceTurn}
              onSelectTurn={setActiveTraceTurn}
            />
          </section>
        </main>
      )}
    </div>
  );
}
