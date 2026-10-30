# Chaukas — Regulatory Compliance Map

> **Owner:** Member 2 (controls) · Member 3 (UI surfaces + deck slide 9)
> **Purpose:** every regulatory requirement we claim → the exact control in Chaukas → where it lives (file / table) → how we prove it (demo scene / test). If a row isn't **Built**, the deck must not claim it as built.
>
> ⚠️ **Verify before slides:** section numbers and requirement wording below are our reading of the regulations. Before anything goes on a slide, check it against the official text (RBI website, MeitY gazette). Say "aligned with", not "certified compliant" — accountability stays with the regulated entity (Paytm / the lender).

**Status legend:** ✅ Built (P0) · 🟡 P1 (if time) · 🔵 P2 / roadmap (deck only, say "planned")

**Regulations in scope**
| Code | Regulation | Why it applies to us |
|------|-----------|----------------------|
| **R** | RBI **FREE-AI** framework (Aug 2025) — Framework for Responsible and Ethical Enablement of AI; 7 sutras, 26 recommendations | AI used by a regulated payments/lending business, touching customer money |
| **L** | RBI **Digital Lending Directions, 2025** (consolidating the 2022 digital lending guidelines) | We make loan offers inside the conversation |
| **P** | RBI directive on **storage of payment system data** (2018) | Settlement / payout data is payment data |
| **D** | **DPDP Act 2023** (Digital Personal Data Protection Act) + DPDP Rules | We process merchants' personal data (name, phone, VPA, PAN, bank account) |

---

## 1. RBI FREE-AI — responsible AI

| ID | Requirement | Chaukas control | Where | Proof | Status |
|----|-------------|-----------------|-------|-------|:------:|
| R1 | Customers must know they're dealing with AI | First message of every session: "Main Chaukas hoon, Paytm ka AI assistant" + "AI" badge in chat | `chaukas/compliance/disclosure.py`, `chaukas/gateway/session.py`, UI | Scene 1 | ✅ |
| R2 | Human oversight; customer can reach a human | Handoff with decision brief; intent `human_request` ("insaan se baat karao") always → handoff; "Talk to a human" button | `chaukas/agents/handoff.py`, `handoffs` table, UI | Scene 3 | ✅ |
| R3 | Explainability ("understandable by design") | Every decision carries `reason_code` + human-readable `reason`; lender returns `reason_codes`; brief lists verified / done / refused + why | `audit_log.reason_code`, `chaukas/agents/guardrail.py`, `chaukas/integrations/lending.py` | Scenes 2, 3, 5 | ✅ |
| R4 | Accountability + audit trail | Append-only `audit_log` (DB trigger), `actor` column (agent / merchant / human / system), `ticket_events` | `data/schema.sql`, `chaukas/observability/audit.py` | Scene 5 (UPDATE → ABORT) | ✅ |
| R5 | Safety: limits, fail-safes, kill switch | Deterministic guardrail (10 checks), value + daily limits, `executions_require_allow` trigger, rollback tokens, **`disabled_actions` kill switch** in policy | `chaukas/policy/engine.py`, `config/policy.yaml` | Scenes 2, 4; `tests/test_guardrail.py` | ✅ |
| R6 | Fairness, no discrimination | Simulated lender uses **only cashflow features** — never name, gender, location, language, religion. Test: same cashflow with different name / `preferred_lang` → identical decision | `chaukas/integrations/lending.py`, `tests/test_fairness.py` | Eval | 🟡 |
| R7 | Testing before deployment, red-teaming | Golden set + red-team suite as a merge gate; "0 unsafe actions" hard gate | `eval/`, `data/golden_set.json`, `data/redteam_set.json` | Scene 5 scorecard | ✅ |
| R8 | Monitoring + incident logging | Per-step trace spans (latency, cost, model); every BLOCK on an attack is an audit row | `chaukas/observability/trace.py` | Scene 5 | ✅ (alerting 🔵) |
| R9 | Model governance / inventory | Model per agent in `config/models.yaml`, prompts versioned (`*.v1.txt`), model name recorded in every span | `config/models.yaml`, `prompts/` | Trace panel | ✅ |

## 2. RBI Digital Lending — the loan offer

| ID | Requirement | Chaukas control | Where | Proof | Status |
|----|-------------|-----------------|-------|-------|:------:|
| L1 | **Key Fact Statement (KFS)** with APR, fees, tenure shown **before** the borrower agrees | Offer card shows KFS (mock values); `offers.kfs_shown_at` must be set before `accepted` — **DB CHECK enforces it** | `offers.kfs_json`, `offers.kfs_shown_at`, UI KFS card | Scene 1 | ✅ |
| L2 | Name the regulated lender | `offers.lender_name` shown on the card ("Offered by <Demo NBFC> via Paytm") | `offers.lender_name`, `config/lender_sim.yaml` | Scene 1 | ✅ |
| L3 | Explicit borrower consent; no auto-acceptance | `create_offer` always NEEDS_CONFIRMATION (`CONSENT_REQUIRED`); acceptance only on CONFIRM / button | `chaukas/agents/guardrail.py` check 10 | Scene 1 | ✅ |
| L4 | Credit decision belongs to the regulated lender | Simulated lender decides eligibility + amount; Chaukas only decides **whether and when** to offer | `chaukas/integrations/lending.py`, design B4.1 | Deck slide 11 | ✅ |
| L5 | Grievance redressal contact | Grievance contact in KFS and in the disclosure message | `compliance/disclosure.py`, `kfs_json.grievance_contact` | Scene 1 | ✅ |
| L6 | Borrower can exit the loan in a cooling-off / look-up period | Lender-side, after disbursal — **out of scope** (we only make the offer). ⚠ Our "offer cooling-off" (don't re-offer for 7 days after a decline) is a **different thing** — see decision D14 | — | — | 🔵 |
| L7 | Collect only needed data, with consent | Lender gets cashflow features only; purpose-specific consent `loan_offer` | `consents` table | — | ✅ |

## 3. RBI payment data storage

| ID | Requirement | Chaukas control | Where | Status |
|----|-------------|-----------------|-------|:------:|
| P1 | Payment system data stored only in India | DB local (prototype) / India region (prod). LLM routing rule: **raw-ish context only to the India-hosted core model; the fallback model receives masked/tokenised data only.** Verify each provider's hosting region before claiming | `config/models.yaml`, `chaukas/llm/client.py` | ✅ rule · 🔵 prod hosting |

## 4. DPDP Act 2023 — personal data

| ID | Requirement (section — verify) | Chaukas control | Where | Proof | Status |
|----|-------------------------------|-----------------|-------|-------|:------:|
| D1 | **Notice** before processing: what data, why, rights (s.5) | Disclosure message includes a short notice + link; `notice_version` (hash of the exact wording) recorded. Full notice in Hinglish, Hindi, English. Other languages: AI-disclosure line only, **planned** until a native speaker reviews the translations | `compliance/disclosure.py`, `config/disclosure.yaml`, `consents.notice_version` | Scene 1 | ✅ (hi / en) · 🔵 other languages |
| D2 | **Consent**: free, specific, informed, clear affirmative action (s.6) | Per-purpose consent artefacts (`ai_assistance`, `loan_offer`), append-only history (UPDATE and DELETE both refused by DB triggers); `loan_offer` consent is only valid after the KFS was shown | `consents` table, `compliance/consent.py`, `GET/POST /api/merchants/{id}/consents` | `tests/test_compliance.py` | 🟡 module + API built; rows appear once the gateway/orchestrator call `consent.grant` |
| D3 | Withdrawal as easy as giving consent (s.6) | "Consent wapas lo" → `withdrawn` row; the guardrail then BLOCKs `create_offer` with `CONSENT_WITHDRAWN` (final, no confirmation can lift it) | `compliance/consent.py`, `policy/engine.py` check 7, `POST /api/merchants/{id}/consents` | red-team RT40, `tests/test_guardrail.py` | ✅ guardrail side · UI toggle (M3) pending |
| D4 | Purpose limitation / data minimisation | Each agent gets only the fields it needs (access matrix, design B7.3); guardrail sees **no identity**; LLM never sees raw cashflow or raw PII | `chaukas/privacy/`, agents | Trace panel | ✅ |
| D5 | Reasonable security safeguards (s.8) | Mask at ingestion, tokenise to model, scrub logs, encrypt at rest (prod), only Action agent detokenises one field | `chaukas/privacy/pii.py`, `scrub.py` | Scene 5, PII-leak test | ✅ (encryption 🔵) |
| D6 | Erase when the purpose is served / retention (s.8) | Retention window for `turns`; audit keeps only masked data | `compliance/retention.py`, `config/policy.yaml retention_days` | — | 🔵 |
| D7 | Rights: access summary, correction, erasure (s.11–12) | Merchant data summary + erasure request API | `POST /api/merchants/{id}/erasure` | — | 🔵 |
| D8 | Grievance redressal (s.13) | `human_request` → handoff; grievance contact in notice | `agents/handoff.py`, disclosure | Scene 3 | ✅ |
| D9 | Breach notification (s.8) | Prevention: PII-leak test as a gate; notification process = roadmap | `tests/test_privacy.py` | Eval | 🔵 |
| D10 | Accuracy of data used for decisions (s.8) | Money state always read fresh, never cached; amount must match ledger | `chaukas/agents/context.py`, guardrail check 5 | Scene 4 | ✅ |

---

## 5. Pitch lines (safe to say)

- "Designed to align with **RBI's FREE-AI framework**, **RBI Digital Lending Directions** and the **DPDP Act 2023**."
- "Every money decision is explainable (reason code), auditable (append-only log) and reversible (rollback token)."
- "The most safety-critical agent — the guardrail — sees **no personal data at all**."
- "Loan offers show the Key Fact Statement and the lender's name before consent — the database itself rejects an acceptance without it."
- ❌ Don't say: "RBI-compliant", "certified", "approved". ❌ Don't cite section numbers on slides until verified.

## 6. Who builds what

| Item | Owner |
|------|-------|
| `compliance/disclosure.py` (text per language), `consent.py`, `retention.py` | Member 2 |
| `human_request` intent + handoff | Member 1 |
| KFS fields in `create_offer` + `lender_sim.yaml` (lender name, mock APR/fee/tenure) | Member 1 |
| UI: AI badge, "Talk to a human" button, KFS card on the offer, consent toggle | Member 3 |
| Fairness test, PII-leak test, policy kill switch | Member 2 |
| Deck slide 9 (Safety & compliance) from §5 of this file | Member 3 |
