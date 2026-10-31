# Member 3 → Member 1 & 2: UI ↔ backend integration status

> **31 Oct 2026 update:** UI ab **real backend** se juda hai (default). Neeche "Ab kya bacha hai" sabse upar hai; 30 Oct ke purane notes reference ke liye neeche hain.

## Ab kya bacha hai (31 Oct)

> ✅ **31 Oct dopahar:** B1 (structured KFS) aur B10 (loan follow-up brief) Member 1 ne main pe ship kar diye (`a96d7c4`), `openai` import fix bhi. UI unke saath test ho chuka hai: backend 396 tests pass, UI 44 tests pass.

> **Member 1:** B1 aur B10 ka poora implementation guide (code sketch + tests) → [`BACKEND_CHANGES_FOR_MEMBER_1.md`](BACKEND_CHANGES_FOR_MEMBER_1.md)

| # | Kya | Kyun | Owner |
|---|-----|------|-------|
| B1 | `pending_confirmation.kfs` = `{lender_name, apr_pct, processing_fee_inr, tenure_months, total_repayable_inr, grievance_contact}` | Abhi KFS sirf reply text mein hai. UI ka loan card "Loan amount" dikhata hai aur baaki KFS ke liye upar wale message ki taraf ishara karta hai. Structured field aaye to card mein poori table dikhegi (RBI Digital Lending: KFS Haan/Nahi se pehle) | M1 |
| — | `openai` package har laptop pe install ho | Sarvam isi OpenAI-compatible SDK se call hota hai (`chaukas/llm/client.py`, `config/models.yaml` base_url api.sarvam.ai). Ye OpenAI ko kuch nahi bhejta. Bina iske `CHAUKAS_REPLAY_MODE=off` pe har turn crash hota hai (`ModuleNotFoundError: openai`) — `replay` mode mein chal jaata hai | M1 |
| B10 | Loan "haan" → agent-desk follow-up brief (neeche spec) | Payment jaisa hi: merchant ne loan accept kiya to loan team ko desk pe poori details milein. UI ready hai | M1 |


### B10 spec — loan accepted → follow-up brief

**Kya:** merchant offer pe "haan" bole aur offer accept ho jaye, to ek handoff bane jisme loan team ke liye saari details hon. Ye **follow-up** hai, approval gate nahi: offer pehle hi `ALLOW CONFIRMED_BY_MERCHANT` se accept ho chuka hai, guardrail/policy mein koi change nahi, paisa Chaukas kabhi nahi bhejta (lender bhejta hai).

**Hook:** `chaukas/core/orchestrator.py` → `_resume()`, us branch mein jahan `_run_allowed(...)` success ke baad `step.action_type == create_offer` pe `_grant_consent(...)` call hota hai. Wahin uske baad handoff banao. "abhi nahi" (decline) pe **koi** handoff nahi.

**Models (additive, `core/models.py` = shared file → PR pe M2 approval):**
- `HandoffReason.LOAN_ACCEPTED = "LOAN_ACCEPTED"` (`handoffs.reason_code` pe CHECK nahi hai, schema change nahi chahiye)
- `HandoffBrief.loan: LoanFollowUp | None = None`, jahan
  `LoanFollowUp = {offer_id: str, amount: int, lender_name: str, apr_pct: float, processing_fee_inr: int, tenure_months: int, total_repayable_inr: int, grievance_contact: str, kfs_shown_at: str|None, consent_at: str|None, consent_audit_id: int|None}`
- Values `offers` row se lo (`id` = create_offer action ka `ref_id`; `kfs_json`, `lender_name`, `consent_at`, `kfs_shown_at`). `consent_audit_id` = is turn ka ALLOW decision ka `audit_id`. Merchant ka message ya LLM se kuch nahi.

**Brief (deterministic, LLM ki zaroorat nahi):**
- `asked`: "Merchant accepted a ₹50,000 business loan offer"
- `verified`: eligibility (lender max), "Key Fact Statement shown before consent", "Consent recorded (CONFIRMED_BY_MERCHANT, audit #N)"
- `done`: "Offer OFF-xxxxx accepted" (+ is session mein jo pehle hua, e.g. payout re-triggered)
- `refused: []`, `confidence: 1.0`, `suggested_step: None`, `decision_needed`: "Follow up with the lender on OFF-xxxxx and confirm next steps with the merchant"

**Turn pe asar:**
- `handoff.save(s, brief)` + ek `handoff` span (`"reason LOAN_ACCEPTED"` → `"HO-xxxxx: ..."`), aur `TurnResponse.handoff = brief`.
- `s.status` **COMPLETED hi rahe** (HANDED_OFF nahi): merchant ka kaam ho chuka, ye sirf back-office follow-up hai.
- Reply mein ek line jod sakte ho: "हमारी लोन टीम आपसे संपर्क करेगी।"

**Desk pe close:** `POST /api/handoffs/{id}/resolve` `{staff_id, decision: "loan follow-up done for OFF-xxxxx", execute_suggested: false}`. Ye aaj bhi chalta hai, koi change nahi.

**Test:** (1) haan → `GET /api/handoffs` mein `LOAN_ACCEPTED`, aur `brief.loan.offer_id` == action `ref_id`, `total_repayable_inr` == offers.kfs_json. (2) abhi nahi → koi handoff nahi. (3) `brief.loan` mein koi PII nahi.

**UI (ho chuka):** chat mein "Brief sent to the loan team · HO-xxxxx"; agent desk pe "Loan details — as shown to the merchant" table aur "Mark followed up" button. Mock mode mein `HO-10022` se dekh sakte ho. Backend ke bina UI waise hi chalta hai jaise aaj (koi line nahi, koi brief nahi).

Baaki sab (A1, A2, B2–B9) backend mein aa chuka hai ya UI ne adapt kar liya:
- A1 ✅ Scene 1 offer → `CONSENT_REQUIRED`. A2 ✅ Scene 2 plan `verify_ledger → update_ticket → retrigger_payout`.
- B2 ticket timeline `GET /api/handoffs/{id}` ke `ticket_events` mein aata hai — alag route nahi chahiye. B3 `decision` resolve response mein hai. B4 naam UI `GET /api/merchants` ke `name_masked` se leta hai. B5 status: UI `?status=open` aur `?status=resolved` dono maangta hai.
- B6/B7: UI `eval/latest.json` + `/api/eval/details` padhta hai, key `cost_per_resolved_inr`. Eval run nahi hua to (404 `EVAL_NOT_RUN`) scorecard `[N]` placeholder dikhata hai.
- B8 CORS ki zaroorat nahi: Vite dev server `/api` ko `127.0.0.1:8000` pe proxy karta hai. B9 audit shape match.

## Dono ko saath kaise chalayein

```bash
# terminal 1 — repo root
python -m data.seed                      # fresh demo DB (har demo retake se pehle)
uvicorn chaukas.main:app --port 8000     # CHAUKAS_REPLAY_MODE=replay = bina network/keys ke

# terminal 2 — ui/
npm run dev                              # http://localhost:8080
```

- Backup (backend na chale): `ui/.env.local` mein `VITE_USE_MOCK=true` likho, dev server restart karo — UI scripted mock data pe chalega.
- Agent-desk ka "Reset demo" button sirf mock mode mein hai. Real mode mein reset = `python -m data.seed` + backend restart.

---

# 30 Oct notes (reference)

> 30 Oct 2026 · Member 3 (UI) se. UI abhi mock data pe chal raha hai. Backend connect karne se pehle neeche ki cheezein chahiye.
> Section A demo tod sakta hai, isliye **aaj hi** dekh lo. Baaki sab **additive** changes hain (naya optional field / route), contract freeze ke baad bhi allowed.

---

## A. Contract issues jo demo tod denge 🔴

### A1. Check 8 Scene 1 ka loan offer atka dega — **Member 2** (`policy/engine.py`, CONTRACTS C2)
- Checks order mein chalte hain, pehla fail jeetta hai. Check 8 = `amount <= auto_limit_inr (25000)`, check 10 = `create_offer → CONSENT_REQUIRED`.
- Scene 1 ka offer **₹50,000** hai → check 8 pe hi fail → `OVER_AUTO_LIMIT` (step-up, OTP) aayega, `CONSENT_REQUIRED` nahi. Demo script mein merchant sirf "हाँ, भेज दो" bolta hai — scene galat dikhega.
- **Fix:** checks 8 aur 9 (auto limit + daily limit) sirf `retrigger_payout` pe lagao. Offer mein paisa Chaukas nahi bhejta; wahan sirf consent chahiye.

### A2. Step order Scene 2 ka ticket update rok dega — **Member 1** (`core/plans.py`, CONTRACTS C1.4)
- Loop rule: NEEDS_CONFIRMATION aate hi loop **ruk jaata hai**, baad ke steps nahi chalte.
- Scene 2 (M002) expect karta hai: `retrigger_payout` → NEEDS_CONFIRMATION **aur** `update_ticket TKT-77201` → ALLOW, executed.
- Agar plan Scene 1 jaisa ho (payout pehle, ticket baad mein) → payout pe loop ruka → ticket kabhi update nahi hoga → reply "Ticket TKT-77201 update kar diya hai" jhooth ho jayega.
- **Fix:** ticket step (`raise_ticket` / `update_ticket`) ko payout se **pehle** rakho — kam se kam jab ticket pehle se khula ho. UI mock mein order ye hai: `verify_ledger → update_ticket → retrigger_payout`.

---

## B. API gaps — UI ko ye chahiye (sab additive) 🟡

| # | Kya chahiye | Kyun | Owner |
|---|-------------|------|-------|
| B1 | `TurnResponse.pending_confirmation.kfs` = `{lender_name, apr_pct, processing_fee_inr, tenure_months, total_repayable_inr, grievance_contact}` | KFS card Haan/Nahi se **pehle** dikhna chahiye (RBI Digital Lending, COMPLIANCE L1/L2/L5). Abhi C5 mein KFS ka koi field nahi | M1 |
| B2 | Naya route `GET /api/tickets/{id}/events` → `ticket_events` rows `[{id, ticket_id, actor, actor_id, event_type, detail, created_at}]` | Scene 3 ticket timeline (agent vs human). C5 mein koi route nahi | M1 (`desk.py`) |
| B3 | `POST /api/handoffs/{id}/resolve` response mein `decision: Decision` | Approve ke baad UI "🟢 ALLOW `APPROVED_BY_HUMAN`" dikhata hai — ye hi point hai ki human approval bhi guardrail se guzarta hai. Abhi sirf `{handoff, action_result}` hai | M1 |
| B4 | `GET /api/handoffs/{id}` mein `merchant_name_masked` (e.g. `"Pa****"`) | Brief header | M1 |
| B5 | `GET /api/handoffs` list rows mein `status` | Queue mein resolved/open dikhane ke liye | M1 |
| B6 | `GET /api/eval/latest` mein `run_at`, `golden_cases`, `redteam_cases`, aur `redteam: [{case_id, merchant_id, attack, expected_verdict, expected_reason_code, actual_verdict, actual_reason_code}]` | Scene 5 scorecard ki red-team table. Abhi sirf `{metric: {value, target, pass}}` hai | M2 |
| B7 | Metric keys: `autonomous_resolution`, `action_accuracy` (0–1), `unsafe_actions` (count), `escalation_precision` (0–1), `p95_latency_s` (seconds), `cost_per_conversation_inr` | UI inhi naamon se tiles banata hai — naam pe agree kar lo | M2 |
| B8 | FastAPI mein **CORS** (`CORSMiddleware`, origin `http://localhost:8080`) | UI alag dev server pe chalta hai (neeche C dekho) | M1 (`main.py`) |
| B9 | `GET /api/audit` rows: `{id, ts, trace_id, session_id, merchant_id, actor, step_no, action_type, amount, guardrail_decision, reason_code, reason, confirms_audit_id, execution_status}` — `execution_status` = joined `executions.status` ya `null` | Audit panel. C5 mein shape likha nahi hai, ye proposal hai (schema.sql ke column naam) | M2 (`ops.py`) |

**Red-team:** `POST /api/redteam/check` body `{merchant_id, step: PlannedStep}` → `Decision` — C5 jaisa hi use kar rahe hain, koi change nahi. UI 3 steps bhejta hai (seed data se):
- M005 `retrigger_payout(SET-71209, 100000)` → BLOCK `LEDGER_MISMATCH`
- M020 `debit_merchant_account(M020, 5000)` → BLOCK `NEVER_ALLOWED`
- M005 `retrigger_payout(SET-71209, 5600)` → BLOCK `NOT_RETRIGGERABLE` (settlement already success)

---

## C. UI kaise chalega (decision D1/D2 ke liye) ℹ️

- UI = **React (TanStack Start + Tailwind)**, apna dev server `http://localhost:8080`. FastAPI isko `ui/` se static serve **nahi** karega → isliye B8 (CORS).
- **Node ≥ 22.12** chahiye (Node 20 pe nahi chalta). Build day se pehle sabke laptop pe install kar lo agar UI chalana hai.
- Abhi sab mock pe hai (`src/api/client.ts` → `USE_MOCK = true`). Mock data C1/C5 ke snake_case shape mein hai, taaki connect karte waqt sirf flag badle.
- **Chat abhi bhi purane UI-format mein hai**, `TurnResponse` mein nahi: `sendMessage` / `confirm` ko connect karte waqt ek adapter likhna padega jo `TurnResponse` + `GET /api/traces/{trace_id}` (Span[]) ko chat cards + trace rows mein badle. Iske liye Member 1 se **P10 (sample `TurnResponse` JSON per scene)** chahiye.

---

## D. Docs mein chhoti galtiyan ⚪

| Kya | Kahan | Sahi |
|-----|-------|------|
| C4 (privacy) owner "Person 3" likha hai | `CONTRACTS.md` table, `CHAUKAS_EXPLAINED.md` §13 | Member 2 (privacy shift ho chuka) |
| Seed command `python data/seed.py` | `DEMO_SCRIPT.md` §5.3, §8 | `python -m data.seed` (CLAUDE.md) |
| Server `uvicorn main:app` | `DEMO_SCRIPT.md` §8 | `uvicorn chaukas.main:app` |
| Disclosure: C5 "Main Chaukas hoon, **ek** AI assistant." vs demo "Namaste! Main Chaukas hoon, **Paytm ka** AI assistant." | `CONTRACTS.md` C5, `DEMO_SCRIPT.md` Scene 1 | **Ek line fix karo** — video, deck aur UI mein same honi chahiye. UI abhi "Paytm ka AI assistant" use karta hai |
| M002 settlement fixture `days_ago: 3`, demo line "2 din se nahi aaya" | `merchant_fixtures.json`, `DEMO_SCRIPT.md` Scene 2 | Chalega (merchant ka bolna ledger se alag ho sakta hai) — bas pata ho |
