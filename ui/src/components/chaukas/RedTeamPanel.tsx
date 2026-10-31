import { useEffect, useState } from "react";
import { ShieldAlert, ShieldCheck, Skull } from "lucide-react";

import { getRedteamAttacks, redteamCheck } from "@/api/client";
import type { Decision, RedteamAttack, Verdict } from "@/lib/chaukas-types";
import { cn } from "@/lib/utils";

import { StepCall } from "./StepCall";
import { VerdictPill, verdictBorderClasses, verdictTextClasses } from "./VerdictPill";

type Result =
  | { status: "idle" }
  | { status: "checking" }
  | { status: "done"; decision: Decision }
  | { status: "error"; message: string };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function ResultBox({ result, checkNo }: { result: Result; checkNo: number }) {
  if (result.status === "idle") {
    return (
      <div className="flex h-full min-h-[132px] flex-col items-center justify-center gap-1.5 rounded-2xl border border-dashed border-border text-center">
        <ShieldCheck className="size-7 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Not sent yet</p>
      </div>
    );
  }
  if (result.status === "checking") {
    return (
      <div className="flex h-full min-h-[132px] items-center justify-center rounded-2xl border border-border bg-surface">
        <p className="animate-pulse text-base font-semibold text-navy">Guardrail checking…</p>
      </div>
    );
  }
  if (result.status === "error") {
    return (
      <div className="flex h-full min-h-[132px] items-center justify-center rounded-2xl border border-block/40 bg-block/5 p-4">
        <p className="text-sm text-block">{result.message}</p>
      </div>
    );
  }

  const { decision } = result;
  const verdict = decision.verdict as Verdict;
  return (
    <div
      className={cn(
        "trace-in h-full min-h-[132px] rounded-2xl border-l-4 p-4 shadow-[var(--shadow-soft)]",
        verdictBorderClasses[verdict],
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <VerdictPill tone={verdict} className="px-3 py-1 text-sm">
          {verdict === "BLOCK" ? "🔴 BLOCK" : verdict}
        </VerdictPill>
        <span className="font-mono text-xs text-muted-foreground">
          check #{checkNo} · audit #{decision.audit_id ?? "—"} · actor system
        </span>
      </div>
      <div
        className={cn("mt-2 text-2xl font-extrabold tracking-tight", verdictTextClasses[verdict])}
      >
        {decision.reason_code}
      </div>
      <p className="mt-1 text-base leading-snug text-foreground">{decision.reason}</p>
      <p className="mt-2 text-sm font-semibold text-muted-foreground">
        Not executed · no money moved
      </p>
    </div>
  );
}

export function RedTeamPanel() {
  const [attacks, setAttacks] = useState<RedteamAttack[]>([]);
  const [results, setResults] = useState<Record<string, Result>>({});

  useEffect(() => {
    getRedteamAttacks()
      .then(setAttacks)
      .catch((error) => console.error("getRedteamAttacks failed", error));
  }, []);

  const busy = Object.values(results).some((r) => r.status === "checking");

  const send = async (attack: RedteamAttack) => {
    setResults((prev) => ({ ...prev, [attack.id]: { status: "checking" } }));
    try {
      const [decision] = await Promise.all([
        redteamCheck(attack.merchant_id, attack.step),
        sleep(450), // keep the "checking" beat visible on screen recordings
      ]);
      setResults((prev) => ({ ...prev, [attack.id]: { status: "done", decision } }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setResults((prev) => ({ ...prev, [attack.id]: { status: "error", message } }));
    }
  };

  const sendAll = async () => {
    for (const attack of attacks) await send(attack);
  };

  const reset = () => setResults({});

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex shrink-0 flex-wrap items-center gap-4 border-b border-border px-6 py-4">
        <span className="flex size-11 items-center justify-center rounded-xl bg-block/10 text-block">
          <Skull className="size-6" />
        </span>
        <div className="min-w-0">
          <h2 className="text-xl font-extrabold text-ink">
            Red team: assume the LLM is fully compromised
          </h2>
          <p className="text-base text-muted-foreground">
            These steps skip every agent and go straight to the guardrail. It only decides — nothing
            is ever executed.
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={reset}
            disabled={busy}
            className="rounded-xl border border-border bg-card px-4 py-2.5 text-base font-semibold text-foreground transition-colors hover:bg-accent disabled:opacity-50"
          >
            Reset
          </button>
          <button
            type="button"
            onClick={sendAll}
            disabled={busy || attacks.length === 0}
            className="rounded-xl bg-navy px-4 py-2.5 text-base font-semibold text-primary-foreground transition-colors hover:bg-navy/90 disabled:opacity-50"
          >
            Send all to guardrail
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {attacks.map((attack) => {
          const result = results[attack.id] ?? { status: "idle" };
          return (
            <div
              key={attack.id}
              className="grid gap-4 rounded-2xl border border-border bg-surface/60 p-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]"
            >
              <div className="min-w-0 space-y-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <ShieldAlert className="size-5 text-block" />
                  <h3 className="text-lg font-bold text-ink">{attack.title}</h3>
                  <span className="rounded-full border border-border bg-card px-2.5 py-0.5 text-sm text-muted-foreground">
                    {attack.merchant_id} · {attack.merchant_name}
                  </span>
                </div>
                <p className="text-base text-muted-foreground">{attack.story}</p>
                <StepCall step={attack.step} />
                <button
                  type="button"
                  onClick={() => send(attack)}
                  disabled={busy}
                  className="rounded-xl border border-navy bg-card px-4 py-2 text-base font-semibold text-navy transition-colors hover:bg-navy hover:text-primary-foreground disabled:opacity-50"
                >
                  Send to guardrail →
                </button>
              </div>
              <ResultBox result={result} checkNo={attack.check_no} />
            </div>
          );
        })}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-6 py-3 text-base text-foreground">
        <span className="font-bold">Deterministic Python, no LLM.</span> Same step → same decision,
        every time. <span className="font-bold">BLOCK is final</span> — no merchant or human
        confirmation can override it.
      </div>
    </div>
  );
}
