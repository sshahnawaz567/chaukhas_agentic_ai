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
| R6 | Fairness, no discrimination | Simulated lender uses **only cashflow features** — never name, gender, location, language, religion. Test: same cashflow with different name / `preferred_lang` → identical decision | `chaukas/integrations/lending.py`, `tests/test_fairness.py` | Eval; `tests/test_fairness.py` (code reads only cashflow_features; changing name / language / device changes nothing, for all 20 merchants, in the lender and in the guardrail's offer gating) | ✅ |
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
| L6 | Borrower can exit the loan in a cooling-off / look-up period *Checked 31 Oct 2026: the 2025 Directions leave the cooling-off length to the lender's board, minimum one day; an older rule of 3 days or 1 day is reported for the 2022 guidelines. Lender-side, so out of scope for us.* | Lender-side, after disbursal — **out of scope** (we only make the offer). ⚠ Our "offer cooling-off" (don't re-offer for 7 days after a decline) is a **different thing** — see decision D14 | — | — | 🔵 |
| L7 | Collect only needed data, with consent | Lender gets cashflow features only; purpose-specific consent `loan_offer` | `consents` table | — | ✅ |

## 2b. Shop insurance (additive, v3.3): same pattern as the loan offer

Chaukas recommends the cover that fits and records the merchant's interest. It never issues a policy, never charges a premium and moves no money. All insurer names, covers and premiums are ILLUSTRATIVE mock values (`config/insurance_sim.yaml`).

| # | Requirement | How we meet it | Where | Test | Status |
|---|-------------|----------------|-------|------|:---:|
| I1 | The merchant knows who offers it and that figures are illustrative | The offer names the insurer, says "illustrative", and shows the grievance contact (kept unmasked as a public contact) | `config/insurance_sim.yaml`, `agents/reply.py` templates | `tests/test_insurance.py` | ✅ (partner and figures are mock) |
| I2 | Explainable recommendation | Deterministic rules over business category, sales, device and PAST support tickets, with reason codes (`CATEGORY_ELECTRONICS`, `DEVICE_TICKET_HISTORY`, ...). The guardrail calls the same function, so offer and permission cannot disagree. No LLM | `integrations/insurance.py`, engine check 7 | rules for all 20 merchants, fairness test | ✅ |
| I3 | Consent per purpose, withdrawal as easy as giving it | Consent purpose `insurance_offer`; the offer needs the merchant's own yes (check 10); a withdrawn consent BLOCKs with `CONSENT_WITHDRAWN`, final | `compliance/consent.py`, `policy/engine.py` | `tests/test_insurance.py`, red-team RT-N1, RT-N5 | ✅ |
| I4 | No mis-selling | Support first (open issue, pending KYC, open handoff all block), one product per conversation, 7-day cooling-off after a no, no second lead for the same product, only the recommended product can be offered | engine check 7, `insurance_leads` | red-team RT-N2..N9, golden I01-I05 | ✅ |
| I5 | Insurance distribution is regulated (IRDAI): only an insurer or an IRDAI-registered intermediary may sell or advise *Checked 31 Oct 2026: IRDAI registers several kinds of distributor (insurers, corporate agents, brokers, web aggregators, insurance marketing firms, individual agents). The exact rules for a recommendation or lead-generation role were NOT verified.* | Prototype = recommendation + interest record only; the licensed partner follows up. **Verify the exact distribution rules before any claim on slides** | roadmap | none | 🔵 |

Safe to say: "Chaukas suggests the cover that fits the shop and never buys it for the merchant: it asks first, records interest, and the licensed insurer takes it from there." Never say "IRDAI-compliant" or "certified".

## 3. RBI payment data storage

| ID | Requirement | Chaukas control | Where | Status |
|----|-------------|-----------------|-------|:------:|
| P1 | Payment system data stored only in India *Checked 31 Oct 2026: RBI circular of 6 April 2018 (DPSS.CO.OD No. 2785): the data must be stored only in India; processing abroad is allowed only if the data is deleted abroad and brought back within one business day / 24 hours. A foreign LLM fallback that only ever sees masked data is our reading, not an RBI ruling: confirm with the regulated entity.* | DB local (prototype) / India region (prod). LLM routing rule: **raw-ish context only to the India-hosted core model; the fallback model receives masked/tokenised data only.** Verify each provider's hosting region before claiming | `config/models.yaml`, `chaukas/llm/client.py` | ✅ rule · 🔵 prod hosting |

## 4. DPDP Act 2023 — personal data

| ID | Requirement (section — verify) | Chaukas control | Where | Proof | Status |
|----|-------------------------------|-----------------|-------|-------|:------:|
| D1 | **Notice** before processing: what data, why, rights (s.5) *Checked 31 Oct 2026: reports say s.5 also lets the person read the notice in English OR any Eighth Schedule language (Marathi and Gujarati are on it). That is why Marathi and Gujarati now have their own notice. Verify s.5 in the Gazette text.* | Disclosure message includes a short notice + link; `notice_version` (hash of the exact wording) recorded. Full notice in Hinglish, Hindi, English. Final languages are Hindi, English, Marathi, Hinglish, Gujarati: Marathi and Gujarati carry the AI-disclosure line AND a full notice of their own, MACHINE-WRITTEN and **not yet read by a native speaker** (config , exposed as `reviewed: false` by `GET /api/disclosure`); every notice also names insurance offers and labels the placeholder grievance contact as demo. Tamil, Telugu, Malayalam, Bengali and Punjabi were removed; those codes fall back to the full Hindi notice | `compliance/disclosure.py`, `config/disclosure.yaml`, `consents.notice_version` | Scene 1 | ✅ hi / hi-Latn / en · 🟡 mr / gu: full notice written, awaiting native review |
| D2 | **Consent**: free, specific, informed, clear affirmative action (s.6) | Per-purpose consent artefacts (`ai_assistance`, `loan_offer`), append-only history (UPDATE and DELETE both refused by DB triggers); `loan_offer` consent is only valid after the KFS was shown | `consents` table, `compliance/consent.py`, `GET/POST /api/merchants/{id}/consents` | `tests/test_compliance.py` | ✅ `ai_assistance` is granted at session start (gateway), `loan_offer` on accept with the KFS shown (orchestrator) |
| D10 | Proactive outreach: Chaukas may *inform* first, but never *move money* first (s.6 consent before action) | A session started by the system (`sessions.trigger_source = 'proactive'`, read fresh from the DB) can never auto-execute `retrigger_payout` or `create_offer`: check 10 returns NEEDS_CONFIRMATION `CONSENT_REQUIRED` even under the limit. One yes covers one action (same action + identical params). List in `config/policy.yaml` `proactive_consent_required` | `policy/engine.py` check 10, `config/policy.yaml`, `data/schema.sql` | `tests/test_guardrail.py` (proactive), red-team RT-P1..P5, golden P01..P08 | ✅ guardrail + red-team · ⏳ golden cases run once Member 1's event watcher lands · notification opt-in / quiet hours are roadmap |
| D3 | Withdrawal as easy as giving consent (s.6) | "Consent wapas lo" → `withdrawn` row; the guardrail then BLOCKs `create_offer` with `CONSENT_WITHDRAWN` (final, no confirmation can lift it) | `compliance/consent.py`, `policy/engine.py` check 7, `POST /api/merchants/{id}/consents` | red-team RT40, `tests/test_guardrail.py` | ✅ guardrail side · UI toggle (M3) pending |
| D4 | Purpose limitation / data minimisation | Each agent gets only the fields it needs (access matrix, design B7.3); guardrail sees **no identity**; LLM never sees raw cashflow or raw PII | `chaukas/privacy/`, agents | Trace panel | ✅ |
| D5 | Reasonable security safeguards (s.8) | Mask at ingestion, tokenise to model, scrub logs, encrypt at rest (prod), only Action agent detokenises one field | `chaukas/privacy/pii.py`, `scrub.py` | Scene 5, PII-leak test | ✅ (encryption 🔵) |
| D6 | Erase when the purpose is served / retention (s.8) | Retention window for `turns`; audit keeps only masked data | `compliance/retention.py`, `config/policy.yaml retention_days` | `tests/test_retention.py`; run the sweep with `python -m chaukas.compliance.retention` (a scheduler is roadmap) | ✅ (scheduling 🔵) |
| D7 | Rights: access summary, correction, erasure (s.11–12) | Merchant data summary (masked) + erasure request: personal fields blanked, both consents withdrawn, only the legally required records kept, receipt returned | `GET /api/merchants/{id}/data-summary`, `POST /api/merchants/{id}/erasure`, `compliance/retention.py` | `tests/test_retention.py` | ✅ access + erasure · 🔵 correction |
| D8 | Grievance redressal (s.13) | `human_request` → handoff; grievance contact in notice | `agents/handoff.py`, disclosure | Scene 3 | ✅ |
| D9 | Breach notification (s.8) | Prevention: PII-leak test as a gate; notification process = roadmap | `tests/test_privacy.py`, `tests/test_pii_leak.py` (whole system: prompts, wire, API, 11 tables, traces, logs) | Eval | 🔵 (the gate ✅, the notification process is roadmap) |
| D10 | Accuracy of data used for decisions (s.8) | Money state always read fresh, never cached; amount must match ledger | `chaukas/agents/context.py`, guardrail check 5, `tests/test_cache_safety.py` | Scene 4 | ✅ |

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

## 7. Verification log (31 Oct 2026)

Done with web searches: official RBI pages where the search returned them, otherwise law-firm and press summaries. **The full official texts were NOT read.** Open the links below before a number or a section goes on a slide.

| Claim in this file | Result | Source | Note |
|---|---|---|---|
| FREE-AI report: Aug 2025, 7 sutras, 26 recommendations | Confirmed | [RBI publication](https://rbi.org.in/scripts/PublicationReportDetails.aspx?ID=1306), [KPMG summary](https://kpmg.com/in/en/insights/2025/08/rbi-free-ai-committee-report-on-framework-for-responsible-and-ethical-enablement-of-artificial-intelligence.html) | Published 13 Aug 2025 by an RBI committee. The sutra names differ between summaries: read RBI section 4.3 before quoting names. The R1-R9 rows are OUR mapping to the themes, not recommendation numbers. |
| RBI Digital Lending Directions, 2025 replace the 2022 guidelines | Confirmed | [RBI notification](https://www.rbi.org.in/scripts/NotificationUser.aspx?Id=12382), [AZB summary](https://www.azbpartners.com/wp-content/uploads/2025/05/AZB-Update-Digital-Lending-Directions-2025.pdf) | Issued 8 May 2025. |
| KFS (APR, fees, tenure) before the borrower agrees; grievance officer named in it | Confirmed (summaries) | RBI notification above, [Mondaq](https://www.mondaq.com/article/1636908/digital-lending-directions-2025) | Summaries disagree on whether the KFS must be digitally signed: we do not claim it. |
| Cooling-off exit period | Partly | [AZB](https://www.azbpartners.com/wp-content/uploads/2025/05/AZB-Update-Digital-Lending-Directions-2025.pdf), [ELP](https://elplaw.in/wp-content/uploads/2025/05/Regulatory-Update-on-RBIs-Consolidated-Digital-Lending-Framework-%E2%80%93-May-2025.pdf) | Length set by the lender's board, minimum one day (2025 Directions). Do not state a number of days. Our own 7-day "do not re-offer after a no" is a Chaukas policy, not a rule. |
| Payment data stored only in India (2018) | Confirmed | [RBI FAQ](https://rbi.org.in/scripts/FS_FAQs.aspx?Id=130), [RBI notification](https://rbi.org.in/scripts/NotificationUser.aspx?Id=11244) | 6 April 2018, DPSS.CO.OD No. 2785. Foreign processing only with return and deletion within one business day / 24 hours. |
| DPDP s.5 notice, s.6 consent (and withdrawal), s.8 safeguards / erasure / breach intimation, s.11-12 access, correction and erasure, s.13 grievance | Section numbers match | [DPDP s.12](https://dpdpa.com/dpdpa2023/chapter-3/section12.html), [s.13](https://dpdpa.com/dpdpa2023/chapter-3/section13.html), [EY on the Rules](https://www.ey.com/content/dam/ey-unified-site/ey-com/en-in/pdf/2025/11/ey-india-dpdp-act-2023-and-rules-2025-pov.pdf) | Secondary (non-government) pages: check the Gazette text. s.8(6) breach intimation is a duty in the Act; the Rules give the form. |
| DPDP Rules, 2025 | Notified Nov 2025 | [Mondaq](https://www.mondaq.com/india/data-protection/1708164/digital-personal-data-protection-rules-2025-notified), [PIB](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf) | Sources say 13 or 14 Nov 2025. Most duties start in phases, about 18 months later (reported 13 May 2027); the start dates for s.6 and s.8 / s.11-13 conflict between sources. Say "aligned with the DPDP Act and Rules", never "compliant". |
| IRDAI: who may sell insurance | Not verified in detail | [IRDAI Corporate Agents Regulations 2015](https://financialservices.gov.in/beta/sites/default/files/2024-11/IRDAI(Regn%20of%20Corporate%20Agents)%20Regulations-2015.pdf), [Cyril Amarchand note](https://corporate.cyrilamarchandblogs.com/2026/01/insurance-distribution-in-india-emerging-channels-compliance-and-data-governance/) | Only the categories of distributor were confirmed. Whether a lead-generation role needs registration was NOT confirmed. Our slide line stays: the insurer or a registered intermediary issues; Chaukas only records interest. |

**Slide wording that is safe:** "aligned with RBI FREE-AI (Aug 2025), RBI Digital Lending Directions 2025, DPDP Act 2023 and Rules 2025". Never "compliant", "certified" or "approved".
