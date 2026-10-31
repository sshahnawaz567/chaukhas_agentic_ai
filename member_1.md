# Member 1 — change log (Agent Core + API)

> Running record of what Member 1's side of the code does and what was changed. Update it with every work session.
> Scope: only Member 1 files (see `MEMBER_1_AGENT_CORE.md` §1). Nothing in Member 2 / 3 files, `CONTRACTS.md`, `data/schema.sql`, `config/policy.yaml` or `requirements.txt` was edited.

**Status (30 Oct 2026):** P0 is built and now runs against **Member 2's real guardrail, privacy, trace, ops and compliance** (`origin/main` merged into `m1/agentic`). `pytest` → 254 passed (whole repo, no network); `python -m eval.redteam` → 40/40, 0 unsafe. Live Sarvam calls work. Gemini fallback has no key yet. **M1 code is not on `main` yet: PR pending.**

---

## 1. What exists now

| Area | File(s) | Notes |
|------|---------|-------|
| Shared models | `chaukas/core/models.py` | CONTRACTS C1 verbatim + C3 return types + C5 `TurnResponse`. Additive fields listed in §3 |
| Plans | `chaukas/core/plans.py` | Cause-aware templates (IFSC / BANK_DOWN failed / pending / KYC), existing-ticket → `update_ticket`, offer step built from the lender's max amount |
| Orchestrator | `chaukas/core/orchestrator.py` | State machine, guardrail loop, pending/confirm resume, handoffs, reply, persistence, human-approve entry point |
| Agents | `chaukas/agents/{intent,context,action,handoff,reply}.py`, `schemas.py` | Intent = LLM + keyword fallback; Context = DB only; Action = idempotent + rollback, only caller of `detokenise()`; Handoff = deterministic brief + LLM wording; Reply = LLM + template fallback |
| Mocks | `chaukas/integrations/{payments,ticketing,lending,_common}.py` | Deterministic, idempotent via `executions`, rollback via `rollback_token` |
| LLM layer | `chaukas/llm/{client,replay,prompt}.py` | OpenAI-compatible client (Sarvam → Gemini), cost per call, replay (`off`/`record`/`replay`), validated calls |
| Gateway | `chaukas/gateway/session.py` | Sessions, turn numbers, per-session monotonic `step_no`, mask at ingestion, disclosure as turn 1 |
| API | `chaukas/api/{chat,desk}.py`, `chaukas/main.py` | All C5 routes owned by M1; C5 error shape; mounts `api.ops` and `ui/` if they exist |
| Prompts | `prompts/{intent,reply,handoff}.v1.txt` | In the user's agent format (see §4) |
| Config | `config/{models,lender_sim,mock,languages,fallback_replies}.yaml` | `fallback_replies.yaml` is new (deterministic replies when the LLM is down) |
| Seam to Member 2 | `chaukas/core/m2_shim.py` | See §2. The stub guardrail now asks consent for `create_offer` and step-up above `policy.yaml auto_limit_inr`, so scenes 1-2 run before Member 2 lands |
| Tests | `tests/test_orchestrator.py`, `tests/test_llm_prompt.py` | No network. Most orchestrator tests use a fake guardrail; two run scenes 1-3 against the REAL one |

Not built yet: `channel/voice.py` (P1), `cache/` (P2), naive-LLM comparison for scene 4 (P1), recordings for replay mode (`recordings/` is empty). `device_issue` template IS built (with a test).

## 2. Member 2 seam (`m2_shim.py`) — what to swap when their code lands

Each function looks up the real implementation lazily; if Member 2's function is missing it uses a `# STUB`. **No change is needed on our side when theirs lands**, but check these:

| Shim function | Real owner / name it looks for | Stub behaviour |
|---------------|-------------------------------|----------------|
| `guardrail_check` | `chaukas.agents.guardrail.check(step, state, confirmation)` | **Always ALLOW** and writes the `audit_log` row the DB trigger needs. Not a safety layer |
| `mask_text`, `mask`, `detect`, `tokenise`, `detokenise` | `chaukas.privacy.pii.*` | Regex masking; in-process token vault |
| `scrub` | `chaukas.privacy.scrub.scrub` | Deep regex mask |
| `emit_span` | (`chaukas.observability.trace`) — **not wired**, writes `traces/{trace_id}.jsonl` itself | Needs the real signature agreed with Member 2 |
| `get_disclosure` | `chaukas.compliance.disclosure.get_disclosure(lang)` or `disclosure_text(lang)` | Short hi-IN / en-IN text, `notice_version="v1-stub"` |

## 3. Additive changes to shared contracts (need the team's OK before the contract is frozen)

All in `chaukas/core/models.py`, all optional, nothing renamed or removed:
- `PlannedStep.session_id` — makes `idempotency_key` (`{session_id}:{step_no}`) self-contained, so a step saved in `sessions.pending_step_json` or a handoff brief can be resumed later.
- `HandoffBrief.pending_audit_id`, `HandoffBrief.confirmation_kind` — the desk needs them to build the `Confirmation` for "Approve & execute".
- `ConversationState.refused`, `pending_meta`, `handoff_id`, `outcome_tags` — orchestrator bookkeeping.
- `TurnResponse.spans` — trace spans of this turn, so the UI trace panel works even before `api/ops.py` exists.
- `lending.create_offer(..., kfs_shown_at=None, trace_id=None)` — two extra kwargs; `kfs_shown_at` is required (the DB rejects `accepted` without it).
- New models in `models.py`: `LedgerStatus`, `PayoutResult`, `Ticket`, `KFS`, `Offer`, `RollbackResult` (C3 return types).

## 4. How agents/prompts are built (user's standard)

Prompt file = `<SYSTEM INSTRUCTION>`, `<CONTEXT>` (`{context}`), `<INSTRUCTION>`, `<USER QUESTION>` (`{user_question}`), `<RULES>`, `<CHAIN OF THOUGHT>`, `<O/P SCHEMA>` (`thought_process` + one result dict).
- Variables are filled with plain `str.format()` (called directly in `llm.prompt.run_validated()`; no helper). Literal braces in a prompt file (the JSON `O/P SCHEMA` block) are written **doubled** (`{{ }}`); only `{context}` and `{user_question}` are real variables. A stray single `{` raises `KeyError`; `tests/test_llm_prompt.py` renders every prompt file to catch that.
- Context is built as XML with `llm.prompt.to_xml()`; every value is XML-escaped, so merchant text cannot close a tag (injection hygiene).
- Output JSON is validated by Pydantic models in `chaukas/agents/schemas.py` (`IntentOutput`, `ReplyOutput`, `HandoffOutput`) with one repair retry; then the typed result is passed on.
- `thought_process` is for debugging only: never shown to the merchant, never written to the DB. It **is** written (scrubbed) to the per-session `logs/session_<id>/llm_calls.log` (decision changed 31 Oct, user request).

## 5. Decisions taken (flag if you disagree)

1. **Step order for a settlement = `verify_ledger → ticket → retrigger → check_eligibility → create_offer`** (ticket *before* the money step). DEMO_SCRIPT scene 1 lists retrigger first and scene 2 lists the ticket first; one fixed order cannot match both, and the ticket must exist even when the payout stops at the guardrail. Member 2's eval step lists must use this order.
2. **Over-limit (`step_up`) creates a handoff and keeps the step pending**; a typed "haan" cannot release it (needs OTP via the confirm endpoint or a human via the desk). Consent (`create_offer`) stays `AWAITING_CONFIRMATION`.
3. **Declining an offer writes an `offers` row with `status='declined'`** (`lending.record_declined_offer`), otherwise the cooling-off check would have nothing to read. CONTRACTS C2 says "silently dropped"; the audit log is untouched.
4. **Human approval (desk)** closes the handoff, sets the session outcome to `resolved_by_human`, and writes `ticket_events` with `actor='human'`. If the guardrail BLOCKs it, the handoff stays open.
5. **Tool failure** → rollback → `executions.status='rolled_back'` → turn status `FAILED` + handoff `ACTION_FAILED`.
6. **Replay mode:** recorded replies are not served verbatim (they would carry stale ticket ids); the deterministic template is used instead. Recorded *intent* and *handoff* wording are served.
7. **Python:** code is compatible with 3.10 (the only version on this machine) and 3.11. A local `.venv/` (gitignored) holds the dependencies.
8. Cost rates in `config/models.yaml` and KFS figures in `config/lender_sim.yaml` are **placeholders**.

## 5b. Live Sarvam findings (30 Oct, first real calls)

- Key + endpoint + auth work (`https://api.sarvam.ai/v1`, Bearer).
- **`sarvam-30b` is deprecated** (400 error). Config now uses **`sarvam-105b-conversations`**: 0.4-0.7 s per intent call, valid JSON 7/7 on the demo messages (Hindi, Hinglish, injection, confirm). Plain `sarvam-105b` is a slow reasoning model (8-18 s, ran out of tokens before the JSON on 3/7), so it is not used.
- Full turn latency with 3 live calls (intent + handoff + reply): ~1-3 s. Cost shown is a placeholder rate.
- Scenes 1 and 2 run end to end on the live model: M001 payout re-sent + offer with KFS + consent -> accepted; M002 ticket TKT-77201 updated, payout held, handoff brief "Approve retrigger of 32,500?".
- **Reply hallucination found and fixed:** early replies claimed "payout re-sent" for a pending settlement (M004) and "team will verify your transfer" with no handoff (M005). Fixes: (1) an explicit `<outcome>` list in the reply context ("NO payout was re-sent" ...), (2) `reply._grounded()` rejects any LLM reply with an id not from the system or a payout claim that did not happen (negation-aware: "not re-sent" is fine) and falls back to the deterministic template. 8 unit tests.
- Injection text (M005) classified `unknown` -> handoff `UNKNOWN_INTENT` (DEMO_SCRIPT allows "settlement_delay or unknown"); the demo script's reply "all settlements successful" appears only when the model says settlement_delay, which varies run to run. Decide in rehearsal whether scene 4 should force that.
- Hindi replies mix English words (settlement, payout, ticket): readable Hinglish, left as is.

## 6. Open items / for the team

- **Gemini fallback is untested** (no `GEMINI_API_KEY`); model name `gemini-3.5-flash-lite` is from the problem statement. With only Sarvam configured, a Sarvam outage drops to keyword intent + template replies (still safe, less natural).
- **Member 2:** their code is merged and wired (guardrail, privacy, disclosure, consent). Still open: `m2_shim.emit_span` writes spans itself; switch it to `observability.trace.emit()` so `/api/traces/{id}` reads one format.
- **Member 3:** `TurnResponse` is the contract; sample JSON per scene can be produced from the tests. `GET /api/handoffs/{id}` also returns `ticket_events` (the timeline for scene 3).
- **Next:** record LLM replays now that the Sarvam key works (`CHAUKAS_REPLAY_MODE=record`, run scenes 1-4); voice (go/no-go 3 PM); naive-agent comparison for scene 4; real-guardrail integration run of scenes 1–3.

## 7. Session log

| Date | What |
|------|------|
| 2026-10-31 | **Short-term credit line (Postpaid-style, simulated)**, branch `m1/credit-line`, M1 + M2 + shared (user asked M1 to do M2's part too: **needs Member 2's PR approval**). Formula (`lender_sim.yaml credit_line`): `limit = floor_1000(min(50k, inflow_30d/30 × 5 × clamp(1 − inflow_cv, 0.5, 1)))`, below 5k = not eligible; looser gates than the term loan. Offered ONLY when the merchant asks in their own words (`credit_line.keywords`, deterministic): M016 → ₹7,000, M008 → ₹8,000, M003 → no (4k < 5k). `product` param (additive, written only for a credit line, so term-loan steps/audit rows are byte-identical) on `check_eligibility` / `create_offer`; `MerchantContext.credit_line`; KFS + `LoanFollowUp` get `product`, `billing_cycle_days`, `interest_free_days`, `late_fee_inr`. **M2 (engine check 7):** cap by the lender answer for THAT product (mislabelled/missing = BLOCK), per-product kill switch `disabled_offer_products`, no credit line within `credit_line_after_loan_days` (30) of an accepted offer. Templates in 5 languages, reply/intent prompts. Golden: G32 (M016 credit line accepted) + G33 (M003 honest no); G10 left to Member 2's attack-format version on main. `pending_confirmation.product` for the UI. 516 tests pass, eval 39/39, red-team 45/45 0 unsafe. Autonomous-resolution metric 50% MISS is pre-existing (same on the base commit). |
| 2026-10-31 | Member 3's injection tasks: (1) `handoff.py`: `decision_needed` comes from the LLM only when a step is pending; every LLM line passes `_safe_line()` (amount not in plan/ledger, or approve/transfer/send without a pending step -> fixed wording). (2) Injection caught in code before any LLM (`config/injection.yaml`, `intent.injection_signals`, English + Hinglish + Hindi patterns) -> `HandoffReason.SUSPECTED_INJECTION` (additive, models.py), brief written by code (`handoff.injection_brief`), injected `transfer` audited once through the guardrail (BLOCK NOT_IN_ALLOW_LIST, never executed), merchant gets the scene-4 line. (3) Prompt rules (second layer). (4) Tests incl. an LLM stub answering 'Approve the transfer of ₹1,00,000?'. Member 2: golden G10 now hands off `SUSPECTED_INJECTION` (update expectation, should_escalate=true). |
| 2026-10-31 | Gujarati templates (fallback replies + proactive notifications). Live: the LLM answered Gujarati merchants in Hindi / romanised Gujarati ~half the time (5 of 6 in the last run); the script check sends those to the Gujarati template -> 6/6 Gujarati replies. Every code in `detect` now has full reply + notification templates (test). Templates written by the assistant: have a native speaker read them before the demo. |
| 2026-10-31 | Marathi (`mr-IN`) added back: detection 5/5 live; the LLM still answers in Hindi ~2 in 5, so `reply._right_language()` adds a Hindi-vs-Marathi word check (`languages.yaml wrong_words / own_words`) and Marathi fallback + proactive templates -> 5/5 Marathi replies live. Gujarati: 1 of 3 live runs the LLM answered in Hindi (caught -> English template); no Gujarati templates yet. |
| 2026-10-31 | Language list cut to what works end to end (live test): `hi-IN`, `hi-Latn` (Hinglish), `en-IN`, `gu-IN`. Dropped ta/bn/te/kn/ml/pa/or (Sarvam replied in Hindi) and mr (Hindi reply, same script). Any other language -> `en-IN` (`languages.yaml unsupported`), answered in English. Live: 6/6 correct, all replies from the LLM in the right language. |
| 2026-10-31 | Language enum: intent O/P SCHEMA `lang` = closed list of 24 codes from `config/languages.yaml` `detect` (22 scheduled languages + en-IN + **hi-Latn = Hinglish in Latin script**, same code as Member 2's disclosure.yaml); `schemas.normalize_lang` maps model answers (aliases, base language) into the list; keyword fallback returns hi-Latn for Romanised Hindi; Hinglish fallback templates; reply prompt gets the language name; `reply._right_script()` rejects a reply in the wrong script (-> template). Live Sarvam: detection 8/8 (hi, hi-Latn, en, ta, bn, mr, te); replies correct for hi-IN / hi-Latn / en-IN; for ta/bn/te Sarvam still writes Hindi -> caught -> English template; Marathi reply comes in Hindi (same script, not caught). |
| 2026-10-31 | Proactive trigger, Member 1 side (PROACTIVE_FEATURE_CHANGES §4), shared-file-free: `core/event_watcher.py` (scan failed settlements from the DB, dedupe by `sessions.trigger_ref`), `orchestrator.handle_event()` (intent known, deterministic notification `agents/notify.py` + `prompts/proactive_notify.v1.txt`), proactive plan puts the payout right after `verify_ledger`, remaining steps resume after the yes (each through the guardrail), decline of a payout no longer hits `record_declined_offer` (KeyError fix), safety net: a proactive money ALLOW without a yes is never executed (`ProactiveConsentViolation`), no `ai_assistance` consent row for a session the merchant did not open, `POST /api/events/scan` (503 `PROACTIVE_NOT_READY` until schema S5). Waiting on: S5 columns, guardrail check 10 rule + S6 (Member 2), `Span.agent` 'watcher' (S4, Member 2; we emit 'gateway' meanwhile), S1-S3 in models.py. Reactive flow verified unchanged. |
| 2026-10-31 | Member 3's `ui/BACKEND_CHANGES_FOR_MEMBER_1.md`: (1) loan accepted -> deterministic `LOAN_ACCEPTED` follow-up brief (`HandoffBrief.loan: LoanFollowUp`, additive in `models.py`), attached in `_finish()` AFTER the reply so reply + replay key do not change; status stays `completed`; desk close keeps outcome `resolved_autonomously`. (2) `pending_confirmation.kfs` (structured KFS, same `build_kfs`). (3) `llm/client._client()` checks the key before importing `openai`. Needs Member 2: `eval/run_eval.py` must not count `LOAN_ACCEPTED` as an escalation (else G01/G15 fail). Needs CONTRACTS C1/C5 note (shared). |
| 2026-10-30 | Merged `origin/main` (Member 2: real guardrail, privacy, trace, ops, compliance). Per Member 2's request: `ReasonCode.CONSENT_WITHDRAWN`; orchestrator refreshes eligibility before the guardrail on a resumed / human-approved `create_offer` (else check 7 BLOCKs it as `OFFER_NOT_ELIGIBLE`); reply text for `CONSENT_WITHDRAWN`; `consents` rows: `ai_assistance` at session start, `loan_offer` (kfs_shown) when an offer is accepted. 2 tests against the real guardrail. 254 tests, red-team 0 unsafe. |
| 2026-10-30 | Sarvam key added: first live calls. Model -> `sarvam-105b-conversations`; stub guardrail made demo-runnable; reply `<outcome>` + grounding guard; handoff question names the action and amount. 50 tests. |
| 2026-10-30 | Removed `render()`; prompts filled by `str.format()` directly with doubled schema braces (per user decision); test added. |
| 2026-10-30 | Built the full P0 skeleton: models, config, prompts, LLM client/replay/prompt layer, mocks, context, plans, intent, reply, handoff, action, orchestrator, gateway, chat + desk API, `main.py`, tests (42 passing). Created `.venv` and installed the dependencies. |
