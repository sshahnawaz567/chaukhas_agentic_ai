# Member 1 — Agent Core

> **Project:** Chaukas (चौकस) · **Team:** Enver AI · **Track 3 — Autonomous AI Teammates**
> **Your role:** Build the brain — orchestrator, planner, tool calling, mock integrations.
> **Full context:** read `CHAUKAS_PROBLEM_STATEMENT.md` + `CHAUKAS_SYSTEM_DESIGN.md` once before starting.

---

## 1. The problem (30-second version)

Paytm already lets merchants *talk* (AI Soundbox, 11 languages). The gap is that when a merchant's query needs an **action** — re-trigger a failed settlement, raise a refund, extend a loan — a human still does it by hand. Chaukas is the AI teammate that **acts**: understands → decides → executes → verifies → escalates, all in one conversation. It handles **customer support and sales together** (fix the issue, then offer a consented loan).

You own the part that makes it *act*.

---

## 2. Your task

Build the **agent core**: the loop that takes a merchant's intent, plans the right actions, and runs them through mock APIs — calling the guardrail (Member 2's code) before every action.

**You own these files:**
```
core/orchestrator.py     # the state machine + plan loop
core/state.py            # ConversationState object
core/agents/intent.py    # Intent & Language Agent
core/agents/context.py   # Context Agent (360°)
core/agents/action.py    # Action Agent (executes tools)
integrations/payments.py # [MOCK] verify_ledger, retrigger_payout
integrations/ticketing.py# [MOCK] raise_ticket
integrations/lending.py  # [MOCK] check_eligibility, create_offer
data/merchant_fixtures.json
```

---

## 3. What each piece does

**`state.py` — `ConversationState`**
One object passed through the whole loop. Agents read from it, append to it, never hold hidden state. (Full schema in system design B2.) Build this first — everyone depends on it.

**`intent.py` — Intent & Language Agent**
One LLM call, structured JSON out: `{intent, lang, urgency, track: support|sales}`. If confidence is low → `intent="unknown"` → orchestrator sends to handoff. The message it sees must already be PII-masked (Member 3 / privacy module handles that).

**`context.py` — Context Agent (360°)**
**No LLM call** — deterministic fetch from `merchant_fixtures.json`. Returns `{gmv_30d, settlements[], tickets[], device, loan_eligibility}`. Fetch only what the intent needs. **Money state (settlement/payout status) is always fresh, never from cache.** Non-money context can use the L2 cache.

**`orchestrator.py` — the heart**
- Takes `intent + merchant` → builds a `plan` (ordered list of steps).
- Use **hard-coded plan templates per intent** for the prototype (reliable beats clever). Start with one: `settlement_delay → [verify_ledger, retrigger_payout, raise_ticket, evaluate_loan_offer]`.
- Loop: `for step in plan: guardrail.check(step) → if ALLOW: action.run(step); else: handoff`.
- **Invariant you must enforce:** guardrail is called before *every* action. There is no code path to action that skips it.

**`action.py` — Action Agent**
Executes an ALLOWed step via `integrations/*`. Idempotent: `idempotency_key = f"{session}:{step}"`. On error → attempt rollback via the token the guardrail issued → mark failed → let orchestrator decide.

**`integrations/*` — all mock**
Return deterministic fixtures keyed by id, so eval runs are repeatable. Example shapes are in system design B5. Keep them dumb — they just return canned data.

---

## 4. Build order (your part)

1. `state.py` — get the `ConversationState` dataclass right; share it with the team immediately.
2. `integrations/*` mocks returning fixtures.
3. `context.py` (deterministic, easiest to test).
4. `orchestrator.py` with the one `settlement_delay` template + `action.py`, calling a **stub** guardrail that always returns ALLOW (so you're not blocked on Member 2).
5. Swap the stub for Member 2's real guardrail once it's ready.
6. `intent.py` (the LLM piece) last — mock the intent output while testing the loop.

> Golden rule: get the **text loop working end-to-end with stubs** before polishing any single agent.

---

## 5. Dependencies & handoffs

- **You → everyone:** `state.py` must land first; the whole team builds against it. Freeze its shape early, change it only by team agreement.
- **Member 2 (Guardrail) → you:** you call `guardrail.check(step)`. Agree on the exact signature together: input = a `PlannedStep`, output = `Decision{verdict, reason, rollback_token}`. Use a stub until theirs is ready.
- **Member 3 (Privacy) → you:** intent agent receives already-masked text; action agent uses `detokenise()` only for the exact field a tool needs. Import from `privacy/`.
- **You → Member 2 (Eval):** your mock integrations + fixtures are what the eval harness replays against. Keep fixtures stable.

---

## 6. Definition of done

- [ ] `settlement_delay` runs end-to-end: intent → context → plan → guardrail → action → result, using mocks.
- [ ] Guardrail is provably called before every action (no bypass path).
- [ ] Actions are idempotent (running twice = same result, no double payout).
- [ ] A second intent template added (e.g. `refund_request`) to prove the pattern generalises.
- [ ] You can explain the orchestrator flow on stage without notes.

---

## 7. Interview / viva prep (judges will ask)

- Why a state machine and not a single big prompt? (deterministic, auditable, debuggable)
- How do you stop the agent from doing an action twice? (idempotency keys)
- What happens if a tool call fails mid-plan? (rollback token → mark failed → handoff)
- Why hard-coded plan templates instead of letting the LLM plan freely? (reliability for a money system; the LLM fills parameters, not the plan structure)
