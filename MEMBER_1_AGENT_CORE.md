# Member 1 — Agent Core + API

> **Project:** Chaukas (चौकस) · **Team:** Enver AI · **Track 3 — Autonomous AI Teammates**
> **Your role:** The brain and the backbone — shared models, orchestrator, LLM agents, mock integrations, and the FastAPI layer the UI talks to.
> **Read first:** `CHAUKAS_EXPLAINED.md` (whole design, Hinglish) → `CONTRACTS.md` (C1, C3, C5 are yours) → `DEMO_SCRIPT.md` §2–3 (what must work on stage).
> **Updated:** 29 Oct 2026. Supersedes the earlier version of this file.

---

## 1. What you own

**Your folders** (full tree with everyone's files: `CONTRACTS.md` §C6). Every file already exists with a docstring — open it, read the docstring, write the code.

```
chaukas/
├── main.py                    FastAPI app (includes api/*, serves ui/)
├── api/chat.py                /api/merchants, /api/sessions/*, /confirm, voice (P1)          C5
├── api/desk.py                /api/handoffs/* — agent-desk, human approve                    C5
├── gateway/session.py         session + turn no, AI disclosure (text from compliance/), mask at ingestion
├── core/models.py             ★ ALL shared models + enums — LAND FIRST                       C1
├── core/orchestrator.py       turn state machine + loop                                      C1.4
├── core/plans.py              plan templates per intent / cause
├── agents/intent.py           Agent 1 — Intent & Language (LLM + keyword fallback)
├── agents/context.py          Agent 2 — Context 360° (DB, no LLM)
├── agents/action.py           Agent 4 — Action (idempotent, rollback, only detokenise caller)  C3
├── agents/handoff.py          Agent 5 — Handoff brief
├── agents/reply.py            Reply in merchant's language
├── integrations/payments.py   [MOCK] verify_ledger, retrigger_payout, cancel_payout           C3
├── integrations/ticketing.py  [MOCK] raise/update/void ticket                                C3
├── integrations/lending.py    [MOCK] simulated lender, build_kfs, create/withdraw offer       C3
├── llm/client.py              one client, Sarvam core / Gemini fallback, cost per call
├── llm/replay.py              record + replay LLM responses (demo safety net)
├── cache/                     P2
└── channel/voice.py           P1 — Saaras STT -> loop -> Bulbul TTS
config/  models.yaml · lender_sim.yaml · mock.yaml · languages.yaml
prompts/ intent.v1.txt · reply.v1.txt · handoff.v1.txt
recordings/                    replay files
tests/test_orchestrator.py
```

(`agents/guardrail.py` is Member 2's — you only **call** it.)

**Compliance work that is yours** (`COMPLIANCE.md`):
- `human_request` intent → always handoff `HUMAN_REQUESTED` (R2, D8).
- `build_kfs()` + KFS in the offer: lender name, mock APR / fee / tenure / total repayable / grievance contact from `lender_sim.yaml`; set `kfs_shown_at` when the offer is presented, **before** consent (L1, L2, L5).
- LLM routing rule: the fallback model only ever receives masked/tokenised data (P1).
- Gateway sends the disclosure + notice as the first message (R1, D1) — text comes from `compliance/disclosure.py`.

---

## 2. Key design points (what changed from the old plan)

- **Models are Pydantic, in ONE file** (`core/models.py`), not a dataclass. Everyone imports from here.
- **Intent list:** `settlement_delay`, `loan_inquiry`, `device_issue`, `refund_request` (always handoff — no refund tool, by design), `confirm`, `deny`, `human_request` (always handoff), `unknown`.
- **Plans branch on the settlement cause** (see `merchant_fixtures.json → _meta.cause_to_plan`):
  - `IFSC_MISMATCH` → retrigger only if `bank_details_updated_at` is after the failure, else handoff `BANK_DETAILS_NOT_UPDATED`
  - `BANK_DOWN` failed → retrigger · `BANK_DOWN` pending → don't retrigger, ETA + ticket
  - `KYC_PENDING` → never retrigger, ticket + handoff, reply carries static KYC link
- **Existing open ticket for the same settlement → `update_ticket`, never a duplicate** (M002).
- **Amounts never come from the merchant's message** — always from the ledger.
- **Multi-turn:** a NEEDS_CONFIRMATION step is saved to `sessions.pending_step_json`; next turn `confirm` / `deny` resumes it → **guardrail runs again** with a `Confirmation`.
- **`step_no` is monotonic per session** (not per turn) — idempotency key `{session_id}:{step_no}` must stay unique across turns.
- **Context Agent reads settlements FRESH** every turn. Never cached.
- **Over-limit in the demo is approved by a human** (agent-desk, `POST /api/handoffs/{id}/resolve`), so merchant OTP is P1.
- **Lender is simulated:** `check_eligibility()` returns `{eligible, max_amount, reason_codes}` from `cashflow_features` + `config/lender_sim.yaml`. The LLM only sees `reason_codes`, never raw cashflow numbers.

---

## 3. Priorities (driven by the demo)

| Priority | Item | Demo scene |
|----------|------|:---:|
| **P0** | `core/models.py` — **land first**, everyone builds on it | all |
| **P0** | Mocks + context agent + `settlement_delay` template with cause branching | 1, 2 |
| **P0** | Orchestrator loop calling `guardrail.check()` (stub ALLOW until Member 2's is ready) | 1, 2 |
| **P0** | API: `/api/merchants`, `/api/sessions`, `…/messages`, `…/confirm`, `/api/traces/{id}` | 1, 2 |
| **P0** | Handoff agent + `/api/handoffs`, `…/resolve` (human approve → guardrail → execute) | 3 |
| **P0** | Intent agent (LLM) **+ keyword fallback** | 1, 2, 4 |
| **P0** | Reply agent (LLM) in merchant's language | 1, 2 |
| **P0** | `loan_inquiry` + `confirm`/`deny` resume | 1 |
| **P1** | **Replay mode** — record LLM responses for the 4 demo scenes, serve them if the API/network fails | safety net |
| **P1** | Voice endpoint (Saaras STT → loop → Bulbul TTS), Hindi only — **3 PM cut-off** | 1 |
| **P1** | Naive-LLM-agent comparison for scene 4 | 4 |
| **P1** | `device_issue` template | — |
| **P2** | L1/L2 cache (talk about it, build only if idle) | — |

---

## 4. Before build day (29–30 Oct) — no app code needed

- [ ] **Test API keys today:** Sarvam-30B (and Gemini as fallback). Send ~20 Hinglish/Hindi messages ("paisa nahi aaya", "loan milega?", "QR nahi chal raha", "haan bhejo", the injection text from DEMO_SCRIPT scene 4). Check: correct intent? Stable JSON? Latency?
- [ ] **Draft the 3 prompts** (`intent`, `reply`, `handoff`) and test them on the same messages. Keep them short (TTS cost) and in files.
- [ ] Write the plan templates on paper: for each intent + cause, the exact step list.
- [ ] Confirm with the team: is pre-built code allowed? If **yes** → write `core/models.py` + mocks tonight. If **no** → have the code structure clear in your head.
- [ ] Python version + `requirements.txt` agreed; dependencies pre-installed on your laptop.

---

## 5. Build day (31 Oct)

| Time | You |
|------|-----|
| 9:00–9:30 | Repo up, `core/models.py` pushed (from CONTRACTS C1), DB seeded (Member 2's `seed.py`) |
| 9:30–11:00 | **Walking skeleton:** `/messages` → stub intent → context → plan → stub guardrail → mocks → canned reply. Scene 1 runs end-to-end with stubs. UI (Member 3) can start calling it |
| 11:00–1:30 | Real intent + reply LLM, cause branching, swap in Member 2's real guardrail, confirm/deny resume |
| **1:30 checkpoint** | Scenes 1 + 2 work in the UI |
| 1:30–3:00 | Handoff agent + agent-desk endpoints (scene 3), replay recordings |
| 3:00 | Voice go / no-go |
| 3:00–4:00 | Rehearsal bugs only |
| **4:00** | **Feature freeze** |
| 4:00–5:45 | Support video recording, README run steps, code freeze |

---

## 6. Dependencies

- **You → everyone:** `core/models.py` (C1). Shape is frozen; additive changes only.
- **Member 2 → you:** `guardrail.check(step, state, confirmation=None) -> Decision` (C2), `privacy.mask_text()` / `detokenise()` (C4), `observability.trace.emit()`, DB helpers (`db.py`).
- **You → Member 2:** mocks + plan templates are what eval replays — tell them if any expected step list changes.
- **You → Member 3:** API responses exactly as `TurnResponse` (C5). Give them a sample JSON per scene early, so they can build UI before the backend is real.

---

## 7. Definition of done

- [ ] Scene 1 (M001) and scene 2 (M002) run from the UI with real LLM calls.
- [ ] Scene 3: human approve executes through the guardrail (`APPROVED_BY_HUMAN`).
- [ ] No code path reaches `action.run()` without an ALLOW (and the DB trigger agrees).
- [ ] Running the same step twice → `replayed=True`, no second payout.
- [ ] Network off → replay mode still runs scenes 1–2.
- [ ] You can explain the orchestrator + plan templates without notes.

---

## 8. Judge questions you must own

- Why templates, not free LLM planning? → money flow needs predictable order; the LLM handles ambiguity (language, intent, wording), the plan branches on real data (cause, KYC, pending).
- How is this "agentic" with so little LLM? → understand + decide + act + verify + escalate; decisions are real (cause-aware), just deterministic where money is.
- Duplicate payout? → idempotency key per step, monotonic per session.
- Tool fails mid-plan? → rollback token issued before execution → rollback → handoff `ACTION_FAILED`.
- Why no LangChain? → step-level audit + determinism are the USP; a framework hides them.
- Full list: `CHAUKAS_EXPLAINED.md` §14.
