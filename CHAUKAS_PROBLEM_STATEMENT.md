# Chaukas — Problem Statement & Build Reference

> **Project:** Chaukas (चौकस — "vigilant")
> **Team:** Enver AI (3 members)
> **Event:** Paytm Build for India — AI Hackathon
> **Track:** Track 3 — Autonomous AI Teammates
> **Stage:** Stage 1 submitted · Finals (offline prototype) 31 Oct 2026

This file is the single source of truth for the project. Team members **and** Claude Code should read this before writing any code. It defines *what* we are building, *why*, the *scope boundary*, the *tech stack*, and the *acceptance criteria*. Keep it updated as decisions change.

---

## 1. The track, in one line

> Build an autonomous AI agent that understands context, makes decisions, takes actions, and works alongside human teams — delivering measurable outcomes in **sales or customer service**.

We chose Track 3 because it is the only track that asks for an agent that *acts*, not just answers.

---

## 2. The problem we are solving

Paytm has **already solved the conversation layer**. The AI Soundbox (launched Oct 2025) talks to merchants in 11 Indian languages, gives real-time insights, and has a dedicated support button. So we are **not** building another voice/vernacular bot — that would be pitching Paytm its own product.

**The unsolved problem is the execution layer behind the conversation.** The moment a merchant's query needs an *action* — re-trigger a failed settlement, raise a refund, extend a loan — a human still has to do the work.

Four concrete pain points:

1. **An answer is not a resolution.** A merchant learns their settlement is stuck; fixing it still means a call, a ticket, a queue, and a day of lost business.
2. **Humans are the bottleneck on money.** Every settlement fix, refund and dispute is verified by hand across CRM, ledger and ticketing. Volume scales; headcount can't.
3. **Revenue signals die in the data.** Loan eligibility and upgrade triggers already exist, but they surface as bulk campaigns — never inside the live conversation where intent is highest.
4. **No demo bot survives a risk review.** A generic agent that can touch money, with no limits, no audit trail, no rollback and no RBI-aligned accountability, is a liability.

**One-line problem statement:** *The gap is not understanding — it is verified execution.*

---

## 3. Our solution — Chaukas

Chaukas is an AI teammate that closes the loop: it understands the merchant, decides what the fix actually is, executes it through APIs, **verifies every action against policy before it runs**, and escalates with full context only when it should.

### The 5-stage loop

| Stage | What it does |
|-------|--------------|
| 1. Understand | Full context + language, not just the last utterance |
| 2. Decide | Plans a sequence of concrete actions, not a canned reply |
| 3. Act | Calls APIs: settlement, refund, ticket, loan offer |
| 4. Verify | Guardrail checks limits, consent, reversibility — **before** execution |
| 5. Escalate | Hands a human teammate a decision brief, not a transcript |

### Example (this is the demo we are building)

Merchant says (Hindi): *"पिछले हफ्ते का पैसा अभी तक नहीं आया।"* (Last week's money hasn't come yet.)

Chaukas:
1. Detects intent = `settlement_delay`, language = `hi`, urgency = `high`
2. Fetches context: ₹2.1L GMV (30d), settlement `SET-99213` failed, cause = IFSC mismatch
3. Plans: verify ledger → re-trigger payout → raise ticket → evaluate loan eligibility
4. Guardrail: ₹18,400 < ₹25,000 auto-limit · PII masked · rollback token issued · **ALLOW**
5. Acts: re-triggers payout, opens ticket `TKT-44871` linked to the conversation
6. Replies in Hindi, then asks consent: *"₹50,000 ka loan eligible hai — bhejun?"*

**Result:** one conversation resolves both **customer support** (the settlement fix) and **sales** (the consented loan offer). Support + sales in a single turn.

---

## 4. Does it cover both sales and customer support?

Yes — by design.

- **Customer support** is the core: dispute resolution, tickets, escalation.
- **Sales** is attached to the *same* conversation: once the issue is resolved, Chaukas checks the merchant's 360° context for an eligible loan or upgrade and offers it **with consent**, never pushed.

The sales moment is deliberately placed *after* the problem is solved, because that is when merchant trust is highest. The offer is consent-gated and treated as part of the guardrail, so it never feels like spam.

---

## 5. Architecture — one orchestrator, five agents

Deliberately small. Each agent has a typed contract, a single responsibility, and its own tests, so each can be evaluated, swapped and audited independently.

```
                 ┌─────────────────────────────┐
  Merchant  ───▶ │  Intent & Language Agent     │  (support vs sales, lang, urgency)
  (voice/chat)   └─────────────────────────────┘
                 ┌─────────────────────────────┐
                 │  Context Agent (360°)        │  (ledger, tickets, device, loans)
                 └─────────────────────────────┘
                              │
                 ┌─────────────────────────────┐
                 │  ORCHESTRATOR                │  (typed state machine, plans actions,
                 │  (not a prompt chain)        │   enforces order, records every step)
                 └─────────────────────────────┘
                   │             │            │
         ┌─────────▼───┐ ┌───────▼──────┐ ┌───▼──────────┐
         │ Guardrail   │ │ Action       │ │ Handoff      │
         │ Agent       │ │ Agent        │ │ Agent        │
         │ limits,     │ │ signed,      │ │ decision     │
         │ consent,    │ │ idempotent   │ │ brief to a   │
         │ rollback    │ │ API calls    │ │ human        │
         └─────────────┘ └──────────────┘ └──────────────┘
```

**Rule of thumb:** the Guardrail Agent runs *before* the Action Agent, always. Nothing touches money without passing policy first.

### Two modes (this answers "work alongside human teams")

- **Mode 1 — Merchant-facing:** voice/chat in the merchant's language, resolves autonomously inside policy limits, asks consent before anything irreversible.
- **Mode 2 — Teammate copilot:** the same agent sits inside a support agent's desk / field sales executive's app — pre-fetched context, a drafted resolution, one-click execute, next-best lending action.

**Handoff protocol:** Chaukas never dumps a transcript. It hands over a structured brief — what was asked, what was verified, what it already did, what it refused to do and why, its confidence, and the one decision the human must make.

---

## 6. Tech stack

Paytm's stated direction is applied AI on **open-source foundations**, with small language models tuned for the SMB context and Indian languages. We build to that reality, not around it. Cost per resolved conversation is the design constraint (target < ₹3).

| Layer | Choice | Concrete pick (locked 29 Oct 2026) |
|-------|--------|-------|
| Model routing | Open-source SLM for ~80% of turns; frontier model only for complex planning | **Sarvam-30B** (`sarvam-30b`, Apache 2.0, native Indian + code-mixed Hinglish) as core; **Gemini Flash** (`gemini-3.7-flash` / `gemini-3.5-flash-lite`) as frontier/fallback tier. Both sit behind one OpenAI-compatible client so routing is a swap, not a rewrite |
| Orchestration | State machine with typed tool schemas, deterministic retries, step-level tracing | **Plain Python + FastAPI + Pydantic. NO LangChain / LangGraph** — framework abstractions obscure the determinism and step-level audit trail that *are* our differentiator, and slow debugging in a 2-day build |
| Voice & vernacular | Streaming ASR + TTS, Indian languages, code-mixed Hinglish | **Sarvam Saaras** STT (`saaras:v3`; `saaras:v3-realtime` WebSocket for streaming) + **Sarvam Bulbul** TTS (`bulbul:v3`). Streaming is mandatory (non-streaming = 5s+ waits) |
| Merchant 360 data | SQL + feature layer over settlements, tickets, device, loan eligibility | **SQLite** — single file, zero-setup, deterministic, works offline on stage. NOT Postgres (overkill for a 2-day prototype), NOT Google Sheets (network + auth + rate limits kill the <4s target and the live demo). Seeded from JSON fixtures; same schema → Postgres in prod. **Mocked** for the prototype |
| Action integrations | Idempotent, signed API calls into payments, CRM, ticketing; rollback token per call | **Mocked** deterministic fixtures for the prototype |
| Safety layer | Policy engine, value limits, PII redaction, prompt-injection filters, immutable audit log | **Our own deterministic policy engine** (Python + `policy.yaml` + Pydantic). NOT NeMo Guardrails / Guardrails AI / Llama Guard — those add LLM/abstraction layers that break determinism (an LLM-based guard can be talked into ALLOW). This is our differentiator |

> **Cost sanity check (per voice conversation):** Saaras STT ~₹0.25 (30s audio) + Sarvam-30B LLM ~₹0.03 + Bulbul TTS ~₹0.9 (300-char reply) ≈ **₹1.2** — comfortably under the ₹3 target. TTS is the dominant cost, so keep replies short. Text-only turns are near-free. (Apply to the **Sarvam Startup Program** for free API credits during the build.)

### What we DO build for the prototype
- One workflow end-to-end: **settlement/refund dispute + consented loan offer**
- Orchestrator + the five agents
- Guardrail policy engine with value limits + rollback tokens
- Mock ledger / ticketing / loan APIs (no live money)
- A small eval harness (15–50 cases) + a few adversarial prompts
- Simple UI: merchant chat + agent-desk copilot view
- Hindi voice loop (add after the text loop works)

### What we DO NOT build (out of scope)
- Real Paytm API integrations → use mock services
- Vector DB / RAG → our data is structured, embeddings not needed
- Model fine-tuning → talk about it in the pitch, don't spend build time on it
- Production LLMOps (model registry, drift monitoring, distributed serving)
- Autonomous debit from a merchant account — **never, not in any version**

---

## 7. Guardrail & safety rules (non-negotiable)

These are the rules the Guardrail Agent enforces. Treat them as hard requirements in code.

1. **Value limit:** any money action above the auto-limit (₹25,000) requires explicit merchant step-up confirmation.
2. **Allowed-action list:** the agent can only call tools on an explicit allow-list. Anything else is refused.
3. **Consent before irreversible actions**, and before any sales offer.
4. **Idempotency:** every action call carries an idempotency key; a rollback token is issued *before* execution.
5. **Prompt injection:** instructions are never taken from merchant message content; all tool arguments are schema-validated (e.g. Pydantic).
6. **PII:** masked in logs and before any model call.
7. **Audit:** every automated decision that touches money is logged, explainable, and reversible.
8. **Disclosure:** the merchant is always told they are talking to an AI.

Regulatory anchors: **RBI FREE-AI framework** (Aug 2025 — 7 sutras, 26 recommendations; disclosure, explainability, auditability) and the **DPDP Act 2023** (consent, data minimisation, PII handling). Accountability stays with the regulated entity.

---

## 8. Acceptance criteria (how we know it works)

| Metric | Target | How measured |
|--------|--------|--------------|
| Autonomous resolution of action tickets | ≥ 60% | Golden set replayed against mock ledger |
| Action accuracy (correct action, correct amount) | ≥ 99% | Diff vs human-labelled ground truth |
| Unsafe / unauthorised money actions | **0** | Adversarial + prompt-injection red-team suite |
| Escalation precision | ≥ 90% | Blind review of sampled handoffs |
| p95 latency (voice turn → action ack) | < 4s | End-to-end tracing |
| Cost per resolved conversation | < ₹3 | Token + ASR/TTS metering |

**The hard gate:** zero unsafe money actions is a release blocker, not a KPI. A support agent that is 95% safe with money is unshippable.

> These six are the summary line. The full parameter taxonomy (agentic / finance-safety / LLM / support / sales / operational dimensions), the tooling decision (own pytest harness + promptfoo red-team + DeepEval G-Eval; not Ragas), and the evaluation data-privacy stance are in the system-design doc, **§B8.1–B8.4**. Key privacy point: ~80% of metrics are deterministic and need no model, so most of eval runs fully offline; any LLM-judge runs on masked data or a self-hosted model, so **no merchant PII leaves the boundary, even in testing.**

---

## 9. Team split (3 members)

| Member | Owns | Secondary |
|--------|------|-----------|
| Person 1 | Agent core: shared models, orchestrator, LLM agents, mock APIs, FastAPI layer | Model routing, replay mode, voice backend |
| Person 2 | Guardrail + data + privacy + eval: policy engine, DB/seed, audit, PII masking, golden + red-team suites | Red teaming |
| Person 3 | UI (6 demo panels) + live demo + video + deck + submission | Voice UI (if time) |

Details per member: `MEMBER_1_AGENT_CORE.md`, `MEMBER_2_GUARDRAIL_EVAL.md`, `MEMBER_3_INTERFACE_PRIVACY_DEMO.md`. Shared contracts: `CONTRACTS.md`. Demo plan: `DEMO_SCRIPT.md`.

---

## 10. The demo "wow moment"

Whatever else works or doesn't: **on stage, show the guardrail blocking a live over-limit action.** If a judge sees an unsafe action get stopped by policy in real time, the entire pitch gains credibility. Build and test this path first.

---

## 11. Finals deliverables (31 Oct 2026)

Three things to submit:
1. **Working prototype** (or proof of concept)
2. **Demo video**
3. **Presentation of the prototype built**

Mentors are available during the build. Everyone on the team must be able to explain the approach and the design decisions — evaluation includes explaining *why*, not just showing *what*.

---

## Notes for Claude Code
- Start with a **plain-Python, single-workflow** version before reaching for frameworks.
- Build the **text loop first**, then add voice.
- The **Guardrail Agent runs before the Action Agent** — enforce this in the orchestrator, not by convention.
- All external services (payments, CRM, ticketing, loans) are **mock implementations** returning deterministic fixtures.
- Validate every tool argument against a schema; never trust model-generated arguments for money actions.
- Keep prompts in separate files, version-controlled — not hardcoded in logic.
- Emit a structured trace per run: input, tool calls, arguments, guardrail decision, output, latency, token count.
