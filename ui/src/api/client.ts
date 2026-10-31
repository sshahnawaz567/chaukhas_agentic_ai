import type {
  ActionResult,
  ApiEvalDetails,
  ApiEvalMetric,
  ApiHandoffDetail,
  ApiMerchant,
  ApiSession,
  ApiTurnResponse,
  ConsentPurpose,
  ConsentView,
  MetricKey,
  ProactiveStart,
  AuditRow,
  EvalScorecard,
  BotElement,
  ConfirmResult,
  Decision,
  HandoffDetail,
  HandoffStatus,
  HandoffSummary,
  Merchant,
  MerchantScript,
  PlannedStep,
  RedteamAttack,
  ResolveResult,
  SendResult,
  Session,
  TicketEvent,
  TraceRow,
} from "@/lib/chaukas-types";

import agentdeskJson from "@/mocks/agentdesk.json";
import merchantsJson from "@/mocks/merchants.json";
import m001Json from "@/mocks/M001.json";
import m002Json from "@/mocks/M002.json";
import m005Json from "@/mocks/M005.json";
import greetingJson from "@/mocks/greeting.json";
import fallbackJson from "@/mocks/fallback.json";
import redteamJson from "@/mocks/redteam.json";
import auditJson from "@/mocks/audit.json";
import evalJson from "@/mocks/eval.json";

import { toEvalScorecard, toHandoffDetail, toSendResult } from "./adapters";

/**
 * Single source of truth for all Chaukas data. By default every function calls
 * the real FastAPI backend (CONTRACTS C5); the dev server proxies /api to
 * http://127.0.0.1:8000 (vite.config.ts). Set VITE_USE_MOCK=true to run on the
 * scripted demo data in src/mocks/*.json instead (offline backup, tests) — the
 * function names and result shapes stay identical.
 */
export const USE_MOCK = import.meta.env["VITE_USE_MOCK"] === "true";

/** Empty = same origin (the dev-server proxy). Set it to call the API on another host. */
const API_BASE_URL = (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "";

/**
 * Extra demo chips the backend's demo-messages do not have yet: the optional
 * credit-line scene asks M016 in its own words ("postpaid"/"credit line" is what
 * routes to the credit line; a plain "loan" ask stays a term loan → not eligible).
 */
const EXTRA_CHIPS: Record<string, string[]> = {
  M016: ["Postpaid credit line mil sakti hai kya?"],
};

/** Generic chips for merchants that have no scripted demo line. */
const DEFAULT_QUICK_REPLIES = ["मेरा पैसा अभी तक नहीं आया।", "Loan milega kya?"];

/**
 * GET /api/merchants/{id}/demo-messages: the chips for this merchant's own scenario
 * (Hinglish first, then English). Falls back to the local chips if the route fails.
 */
async function demoChips(merchantId: string): Promise<string[]> {
  try {
    const out = await api<{ default_lang?: string; messages: Record<string, { text: string }[]> }>(
      `/api/merchants/${merchantId}/demo-messages`,
    );
    // The merchant's own two messages (default language), never one fixed pair for everybody.
    const lang = out.default_lang ?? "hi-Latn";
    const own = (out.messages[lang] ?? out.messages["hi-Latn"] ?? out.messages["en-IN"] ?? []).map(
      (m) => m.text,
    );
    const chips = [...(EXTRA_CHIPS[merchantId] ?? []), ...own].filter(
      (text, i, all) => text && all.indexOf(text) === i,
    );
    if (chips.length > 0) return chips;
  } catch (error) {
    console.warn("demo-messages failed, using local chips", error);
  }
  return clone(SCRIPTS[merchantId]?.quickReplies ?? DEFAULT_QUICK_REPLIES);
}

/** Real mode: what the UI must remember between calls. */
const merchantNames = new Map<string, string>();
const pendingKinds = new Map<string, Map<string, "consent" | "step_up">>();
const ticketEvents = new Map<string, TicketEvent[]>();

const SCRIPTS: Record<string, MerchantScript> = {
  M001: m001Json as unknown as MerchantScript,
  M002: m002Json as unknown as MerchantScript,
  M005: m005Json as unknown as MerchantScript,
};

const MERCHANTS = merchantsJson as unknown as Merchant[];
const GREETING_TEXT = (greetingJson as { text: string }).text;
const FALLBACK = fallbackJson as unknown as { botText: string; trace: TraceRow[] };
type MockEvent = Omit<TicketEvent, "id" | "ticket_id" | "created_at" | "actor_id"> & {
  actor_id?: string | null;
  minutes_ago?: number;
};
const AGENTDESK = agentdeskJson as unknown as {
  handoffs: (Omit<HandoffDetail, "created_at"> & { minutes_ago: number })[];
  ticket_events: Record<string, (MockEvent & { id: number })[]>;
  resolve: Record<
    "approve" | "decline",
    { decision: Decision | null; action_result: ActionResult | null; events: MockEvent[] }
  >;
};
const AUDIT = auditJson as unknown as { rows: (Omit<AuditRow, "ts"> & { minutes_ago: number })[] };
const EVAL = evalJson as unknown as EvalScorecard;
const REDTEAM = redteamJson as unknown as {
  attacks: RedteamAttack[];
  decisions: Record<string, Decision>;
};

interface SessionState {
  id: string;
  merchantId: string;
  turnIndex: number;
  pending: Set<string>;
}

const sessions = new Map<string, SessionState>();
let idSeq = 0;
const nextId = (prefix: string) => `${prefix}-${String(++idSeq).padStart(4, "0")}`;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  if (!res.ok) {
    // C5 error shape: {"error": {"code", "message"}}
    const body = (await res.json().catch(() => null)) as {
      error?: { code?: string; message?: string };
    } | null;
    throw new ApiError(
      res.status,
      body?.error?.code ?? "HTTP_ERROR",
      body?.error?.message ?? `API error ${res.status} on ${path}`,
    );
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

/** Remember the kind of the step a turn parked, so confirm() can send it back. */
function rememberPending(turn: ApiTurnResponse): void {
  const pending = turn.pending_confirmation;
  if (!pending?.kind || pending.pending_audit_id == null) return;
  const kinds = pendingKinds.get(turn.session_id) ?? new Map<string, "consent" | "step_up">();
  kinds.set(String(pending.pending_audit_id), pending.kind);
  pendingKinds.set(turn.session_id, kinds);
}

export async function getMerchants(): Promise<Merchant[]> {
  if (!USE_MOCK) {
    const rows = await api<ApiMerchant[]>("/api/merchants");
    for (const row of rows) merchantNames.set(row.merchant_id, row.name_masked);
    // Demo merchants first, in scene order; the rest stay available for Q&A.
    const demo = MERCHANTS.map((m) => m.id);
    const rank = (id: string) => (demo.includes(id) ? demo.indexOf(id) : demo.length);
    return [...rows]
      .sort((a, b) => rank(a.merchant_id) - rank(b.merchant_id))
      .map((row) => ({ id: row.merchant_id, name: row.name_masked, demoNote: row.scenario }));
  }
  return clone(MERCHANTS);
}

export async function createSession(merchantId: string): Promise<Session> {
  if (!USE_MOCK) {
    const [out, quickReplies] = await Promise.all([
      post<ApiSession>("/api/sessions", { merchant_id: merchantId }),
      demoChips(merchantId),
    ]);
    return { id: out.session_id, merchantId, greetingText: out.disclosure, quickReplies };
  }
  const script = SCRIPTS[merchantId];
  if (!script) throw new Error(`Unknown merchant: ${merchantId}`);
  const state: SessionState = {
    id: nextId("SES"),
    merchantId,
    turnIndex: 0,
    pending: new Set(),
  };
  sessions.set(state.id, state);
  return {
    id: state.id,
    merchantId,
    greetingText: GREETING_TEXT,
    quickReplies: clone(script.quickReplies),
  };
}

export async function sendMessage(sessionId: string, text: string): Promise<SendResult> {
  if (!USE_MOCK) {
    const turn = await post<ApiTurnResponse>(`/api/sessions/${sessionId}/messages`, { text });
    rememberPending(turn);
    return toSendResult(turn);
  }
  const state = sessions.get(sessionId);
  if (!state) throw new Error(`Unknown session: ${sessionId}`);
  const script = SCRIPTS[state.merchantId];
  if (!script) throw new Error(`Unknown merchant: ${state.merchantId}`);
  const turn = script.turns[state.turnIndex];
  let bot: BotElement[];
  let trace: TraceRow[];
  if (turn) {
    bot = clone(turn.bot);
    trace = clone(turn.trace);
    for (const el of bot) {
      if (el.type === "loan-offer" && el.offer) state.pending.add(el.offer.pendingAuditId);
    }
    state.turnIndex += 1;
  } else {
    bot = [{ type: "text", text: FALLBACK.botText }];
    trace = clone(FALLBACK.trace);
  }
  return { traceId: script.traceId, bot, trace };
}

export async function confirm(
  sessionId: string,
  pendingAuditId: string,
  approve: boolean,
): Promise<ConfirmResult> {
  if (!USE_MOCK) {
    const kind = pendingKinds.get(sessionId)?.get(pendingAuditId) ?? "consent";
    const turn = await post<ApiTurnResponse>(`/api/sessions/${sessionId}/confirm`, {
      pending_audit_id: Number(pendingAuditId),
      approve,
      kind,
    });
    pendingKinds.get(sessionId)?.delete(pendingAuditId);
    rememberPending(turn);
    const consented =
      approve &&
      turn.decisions.some((d) => d.verdict === "ALLOW") &&
      turn.actions.some((a) => a.status === "success");
    const sent = toSendResult(turn);
    const handoffNote = sent.bot.find((b) => b.type === "system-line")?.text;
    const insuranceRef = turn.actions.find(
      (a) => a.action_type === "offer_insurance" && a.status === "success",
    )?.ref_id;
    return {
      botText: turn.reply,
      trace: sent.trace,
      offerState: consented ? "consented" : "declined",
      ...(handoffNote ? { handoffNote } : {}),
      ...(insuranceRef ? { insuranceRef } : {}),
      bot: sent.bot,
    };
  }
  const state = sessions.get(sessionId);
  if (!state) throw new Error(`Unknown session: ${sessionId}`);
  const script = SCRIPTS[state.merchantId];
  if (!script) throw new Error(`Unknown merchant: ${state.merchantId}`);
  const consent = script.consent;
  if (!consent || !state.pending.has(pendingAuditId)) {
    throw new Error(`Unknown pending audit: ${pendingAuditId}`);
  }
  state.pending.delete(pendingAuditId);
  const outcome = approve ? consent.approve : consent.decline;
  const handoffNote = approve ? consent.approve.handoffNote : undefined;
  return {
    botText: outcome.botText,
    trace: [clone(outcome.trace)],
    offerState: approve ? "consented" : "declined",
    ...(handoffNote ? { handoffNote } : {}),
  };
}

/**
 * Proactive demo trigger: POST /api/events/scan for one merchant. The backend opens
 * a session itself (trigger_source "proactive") and Chaukas speaks first about a
 * failed settlement nobody has told the merchant about yet.
 */
export async function simulateEvent(merchantId: string): Promise<ProactiveStart> {
  if (USE_MOCK) throw new Error("The proactive demo needs the real backend (VITE_USE_MOCK is on)");
  const hits = await post<{ session_id: string; turn: ApiTurnResponse }[]>("/api/events/scan", {
    merchant_id: merchantId,
  });
  const hit = hits[0];
  if (!hit) {
    throw new Error(
      `No new failed settlement for ${merchantId}: it was already notified or fixed. ` +
        "Re-seed the DB (python -m data.seed) for a fresh demo.",
    );
  }
  const turn = hit.turn;
  const [disclosure, quickReplies] = await Promise.all([
    api<{ message: string }>(`/api/disclosure?lang=${encodeURIComponent(turn.lang ?? "hi-IN")}`)
      .then((d) => d.message)
      .catch(() => ""),
    demoChips(merchantId),
  ]);
  rememberPending(turn);
  return {
    session: { id: hit.session_id, merchantId, greetingText: disclosure, quickReplies },
    result: toSendResult(turn),
  };
}

// ---------------------------------------------------------------------------
// Consents (DPDP s.6): the chat-settings toggles. Withdrawing is as easy as granting.
// ---------------------------------------------------------------------------

const mockConsents = new Map<string, ConsentView>();

function mockConsentView(merchantId: string): ConsentView {
  let view = mockConsents.get(merchantId);
  if (!view) {
    const empty = { state: null, notice_version: null, at: null } as const;
    view = {
      merchant_id: merchantId,
      purposes: {
        ai_assistance: { state: "granted", notice_version: "mock", at: new Date().toISOString() },
        loan_offer: { ...empty },
        insurance_offer: { ...empty },
      },
    };
    mockConsents.set(merchantId, view);
  }
  return view;
}

/** GET /api/merchants/{id}/consents */
export async function getConsents(merchantId: string): Promise<ConsentView> {
  if (!USE_MOCK) return api<ConsentView>(`/api/merchants/${merchantId}/consents`);
  return clone(mockConsentView(merchantId));
}

/**
 * POST /api/merchants/{id}/consents. The backend refuses to GRANT loan_offer here
 * (only valid right after the KFS was shown), so the UI only offers to withdraw it.
 */
export async function setConsent(
  merchantId: string,
  purpose: ConsentPurpose,
  action: "granted" | "withdrawn",
  sessionId?: string,
): Promise<ConsentView> {
  if (!USE_MOCK) {
    return post<ConsentView>(`/api/merchants/${merchantId}/consents`, {
      purpose,
      action,
      channel: "chat",
      ...(sessionId ? { session_id: sessionId } : {}),
    });
  }
  const view = mockConsentView(merchantId);
  view.purposes[purpose] = { state: action, notice_version: "mock", at: new Date().toISOString() };
  return clone(view);
}

/** Pre-filled malicious steps for the red-team panel. UI-side presets, not an API call. */
export async function getRedteamAttacks(): Promise<RedteamAttack[]> {
  return clone(REDTEAM.attacks);
}

/**
 * Send a hand-crafted step straight to the guardrail ("assume the LLM is fully
 * compromised"). CONTRACTS C5: POST /api/redteam/check — never executes, only decides.
 */
export async function redteamCheck(merchantId: string, step: PlannedStep): Promise<Decision> {
  if (!USE_MOCK) {
    return post<Decision>("/api/redteam/check", { merchant_id: merchantId, step });
  }
  const attack = REDTEAM.attacks.find(
    (a) => a.merchant_id === merchantId && JSON.stringify(a.step) === JSON.stringify(step),
  );
  const decision = attack ? REDTEAM.decisions[attack.id] : undefined;
  if (!decision) throw new Error(`No scripted guardrail decision for this step`);
  return clone(decision);
}

// ---------------------------------------------------------------------------
// Agent-desk (demo scene 3). Mock state lives in memory so approving a handoff
// changes the queue and the ticket timeline, exactly like the real backend would.
// ---------------------------------------------------------------------------

interface DeskState {
  handoffs: HandoffDetail[];
  events: Record<string, TicketEvent[]>;
}

let desk: DeskState | null = null;

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function deskState(): DeskState {
  if (desk) return desk;
  const handoffs = AGENTDESK.handoffs.map(({ minutes_ago, ...rest }) => ({
    ...clone(rest),
    created_at: minutesAgo(minutes_ago),
  }));
  const events: Record<string, TicketEvent[]> = {};
  for (const [ticketId, rows] of Object.entries(AGENTDESK.ticket_events)) {
    events[ticketId] = rows.map(({ minutes_ago, ...row }) => ({
      ...row,
      actor_id: row.actor_id ?? null,
      ticket_id: ticketId,
      created_at: minutesAgo(minutes_ago ?? 0),
    }));
  }
  desk = { handoffs, events };
  return desk;
}

/** Put the agent-desk back to its seeded state (demo retakes, tests). Mock only. */
export function resetAgentDesk(): void {
  desk = null;
}

/** C5: GET /api/handoffs?status= */
export async function getHandoffs(status?: HandoffStatus): Promise<HandoffSummary[]> {
  if (!USE_MOCK) {
    // The list rows carry no status, and the route returns one status at a time:
    // ask for each so resolved handoffs stay visible (greyed) after approval.
    const statuses: HandoffStatus[] = status ? [status] : ["open", "resolved"];
    const lists = await Promise.all(
      statuses.map(async (s) =>
        (await api<Omit<HandoffSummary, "status">[]>(`/api/handoffs?status=${s}`)).map((h) => ({
          ...h,
          status: s,
        })),
      ),
    );
    // Newest first: the handoff just created in the merchant tab is on top.
    return lists
      .flat()
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
  }
  return deskState()
    .handoffs.filter((h) => !status || h.status === status)
    .map((h) => ({
      id: h.id,
      merchant_id: h.merchant_id,
      reason_code: h.brief.reason_code,
      decision_needed: h.brief.decision_needed,
      created_at: h.created_at,
      status: h.status,
    }));
}

/** C5: GET /api/handoffs/{id} */
export async function getHandoff(id: string): Promise<HandoffDetail> {
  if (!USE_MOCK) {
    const raw = await api<ApiHandoffDetail>(`/api/handoffs/${id}`);
    const { detail, events } = toHandoffDetail(raw, merchantNames.get(raw.merchant_id) ?? "");
    if (raw.ticket_id) ticketEvents.set(raw.ticket_id, events);
    return detail;
  }
  const handoff = deskState().handoffs.find((h) => h.id === id);
  if (!handoff) throw new Error(`Unknown handoff: ${id}`);
  return clone(handoff);
}

/**
 * Ticket timeline. The real API returns it inside GET /api/handoffs/{id}, so in
 * real mode this serves what the last getHandoff() call cached.
 */
export async function getTicketEvents(ticketId: string): Promise<TicketEvent[]> {
  if (!USE_MOCK) return clone(ticketEvents.get(ticketId) ?? []);
  return clone(deskState().events[ticketId] ?? []);
}

/**
 * C5: POST /api/handoffs/{id}/resolve. Approving executes the suggested step,
 * which still goes through the guardrail with actor `human`. A brief with no
 * suggested step (human request, loan follow-up) can only be closed: pass
 * approve=false and a `note` saying what the human did.
 */
export async function resolveHandoff(
  id: string,
  staffId: string,
  approve: boolean,
  note?: string,
): Promise<ResolveResult> {
  if (!USE_MOCK) {
    const out = await post<{
      handoff: ApiHandoffDetail;
      decision: Decision | null;
      action_result: ActionResult | null;
    }>(`/api/handoffs/${id}/resolve`, {
      staff_id: staffId,
      decision: note ?? (approve ? "approve" : "decline"),
      execute_suggested: approve,
    });
    const h = out.handoff;
    return {
      handoff: {
        id: h.id,
        status: h.status,
        assigned_to: h.assigned_to ?? staffId,
        human_decision: h.human_decision ?? note ?? (approve ? "approve" : "decline"),
        resolved_at: h.resolved_at ?? new Date().toISOString(),
      },
      decision: out.decision,
      action_result: out.action_result,
    };
  }
  const state = deskState();
  const handoff = state.handoffs.find((h) => h.id === id);
  if (!handoff) throw new Error(`Unknown handoff: ${id}`);
  if (handoff.status === "resolved") throw new Error(`Handoff ${id} is already resolved`);

  // Nothing to execute (loan follow-up, human request): closing it records a note only.
  const script = handoff.brief.suggested_step
    ? AGENTDESK.resolve[approve ? "approve" : "decline"]
    : { decision: null, action_result: null, events: [] as MockEvent[] };
  const resolvedAt = new Date().toISOString();
  handoff.status = "resolved";

  if (handoff.ticket_id) {
    const timeline = (state.events[handoff.ticket_id] ??= []);
    for (const event of script.events) {
      const { minutes_ago: _ignored, ...row } = event;
      timeline.push({
        ...row,
        actor_id: row.actor === "human" ? staffId : (row.actor_id ?? null),
        id: timeline.length + 1,
        ticket_id: handoff.ticket_id,
        created_at: resolvedAt,
      });
    }
  }

  return {
    handoff: {
      id,
      status: "resolved",
      assigned_to: staffId,
      human_decision: note ?? (approve ? "approve" : "decline"),
      resolved_at: resolvedAt,
    },
    decision: clone(script.decision),
    action_result: clone(script.action_result),
  };
}

// ---------------------------------------------------------------------------
// Proof (demo scene 5): audit log + eval scorecard.
// ---------------------------------------------------------------------------

/** C5: GET /api/audit?merchant_id=&session_id= — newest first. */
export async function getAudit(
  filters: { merchant_id?: string; session_id?: string } = {},
): Promise<AuditRow[]> {
  if (!USE_MOCK) {
    const query = new URLSearchParams(
      Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
    ).toString();
    // The API returns oldest first; the panel shows newest first.
    return (await api<AuditRow[]>(`/api/audit${query ? `?${query}` : ""}`)).reverse();
  }
  return AUDIT.rows
    .filter((row) => !filters.merchant_id || row.merchant_id === filters.merchant_id)
    .filter((row) => !filters.session_id || row.session_id === filters.session_id)
    .map(({ minutes_ago, ...row }) => ({ ...clone(row), ts: minutesAgo(minutes_ago) }))
    .sort((a, b) => b.id - a.id);
}

/** C5: GET /api/eval/latest. In mock mode every value is a placeholder (null). */
export async function getEvalLatest(): Promise<EvalScorecard> {
  if (!USE_MOCK) {
    try {
      const latest = await api<Partial<Record<MetricKey, ApiEvalMetric>>>("/api/eval/latest");
      const details = await api<ApiEvalDetails>("/api/eval/details").catch(() => null);
      return toEvalScorecard(latest, details);
    } catch (error) {
      // 404 EVAL_NOT_RUN: show the placeholder scorecard, never invented numbers.
      if (error instanceof ApiError && error.code === "EVAL_NOT_RUN") return clone(EVAL);
      throw error;
    }
  }
  return clone(EVAL);
}
