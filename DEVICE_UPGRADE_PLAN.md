# Device Upgrade — Plan per Member

> **Feature:** Chaukas suggests a device upgrade (QR → AI Soundbox or POS, Soundbox → POS) when a merchant's own transaction pattern crosses a threshold. It does this either **proactively** (automation: the watcher finds the merchant) or **when the merchant asks**.
> **Status:** BUILT (31 Oct 2026), branch `m1/device-upgrade`. Written 15:56 as a plan; the team gave an exception to the 4 PM rule (§7). `tests/test_device_upgrade.py` 36/36, full `pytest` 686 pass, golden 51/51, red-team 46/46 with 0 unsafe. Prices are NOT shown (decision 2), so there is no `device_catalog.yaml`.
> **Depends on:** branch `m1/credit-line` (same files: `models.py`, `policy/engine.py`, `policy.yaml`).
> **Read:** §1–§5 together (everyone), then your own section in §6.

---

## 1. The threshold rule (simulated device advisor)

A deterministic advisor, like the simulated lender. No LLM. All numbers live in `config/device_advisor.yaml`.

```yaml
upgrade_paths:
  qr:
    - to: ai_soundbox        # many small UPI payments -> a spoken confirmation for every payment
      when: {min_txn_per_active_day: 7, max_avg_bill_inr: 400, min_active_days_30d: 20}
    - to: pos                # large bills -> card machine
      when: {min_avg_bill_inr: 500, min_gmv_30d: 75000, min_active_days_30d: 20}
  soundbox:
    - to: pos
      when: {min_avg_bill_inr: 500, min_gmv_30d: 150000, min_active_days_30d: 20}
```

- `avg_bill = gmv_30d / txn_count_30d` (int rupees)
- `txn_per_active_day = txn_count_30d / active_days_30d`
- The soundbox rule ends at ₹400 and the POS rule starts at ₹500, so no merchant matches both.
- Output: `{recommended: bool, to_device, reason_codes}`. Example reason codes: `MANY_SMALL_PAYMENTS`, `LARGE_BILLS`, `LOW_ACTIVITY`.
- **Fairness:** inputs are `cashflow_features`, `gmv_30d` and the **current** device only. Never name, language, location or KYC (KYC is a gating rule in the guardrail, not an advisor input).
- **Limitation (say it in the pitch):** the data has no card vs UPI split. "Large bills → POS" is a proxy from the transaction pattern, not measured card demand.

## 2. Results on `data/merchant_fixtures.json`

| Merchant | Device | Avg bill | Txn/day | Rule says | Gating | Final |
|---|---|---|---|---|---|---|
| **M003** | qr | ₹150 | 10.4 | AI Soundbox | clean | ✅ **Soundbox** |
| **M016** | qr | ₹309 | 7.9 | AI Soundbox | clean | ✅ **Soundbox** |
| **M020** | qr | ₹133 | 8.3 | AI Soundbox | clean | ✅ **Soundbox** |
| M013 | qr | ₹586 | 6.2 | POS | IFSC failure + open ticket | ❌ support first |
| M006 | qr | ₹800 | 4.1 | POS | KYC pending | ❌ |
| M011 | qr | ₹300 | 15.0 | nothing | only 12 active days | ❌ |
| M017 | qr | ₹436 | 5.2 | nothing | open QR ticket | ❌ |
| M012 | soundbox | ₹647 | 12.1 | POS | failed settlement | ❌ until fixed |
| M018 | soundbox | ₹609 | 11.9 | POS | declined offer (cooling-off) | ❌ |

**Gap:** there is no clean POS candidate. Proposal: add **M021** `qr_upgrade_pos` (QR, GMV ₹1,20,000, 160 txn → avg ₹750, 26 active days, KYC verified, no issues). No test hardcodes the number of merchants.

## 3. Flow

**A. Automation (proactive, threshold crossed):**
```
POST /api/events/scan -> watcher runs the advisor for every merchant
  -> threshold crossed + gating clean + no nudge in the last device_nudge_every_days
  -> proactive session, trigger_ref = "device_upgrade:<merchant>:<to_device>" (dedupe)
  -> notification from a TEMPLATE (every number from the data, no LLM):
     "Pichhle 30 din mein aapko 280 payments mile, zyaadatar ₹150 ke aas-paas. AI Soundbox har
      payment pe bolkar confirm karta hai. Kya main field team se request bhej doon? Pricing woh batayenge."
  -> Haan (= consent; no price card, decision 2) -> guardrail ALLOW
  -> request_device_upgrade -> ticket for the field team + DEVICE_UPGRADE_REQUESTED brief
```

**B. Merchant asks:** "naya soundbox chahiye", "POS machine milegi?" → intent `device_upgrade` → advisor → the same card and consent. If the rule does not match, an honest "you do not need it right now".

**Rules:**
- One sales offer per conversation: if a loan or credit line is pending or accepted in the session, no device offer.
- Support first: a device complaint ("QR scan nahi ho raha") gets a ticket, never an upsell.
- Prices are **mock placeholders** (`config/device_catalog.yaml`), not Paytm's real prices.
- Pitch wording: "aligned with", never "compliant"; never claim a device is "free" or "pre-approved".

## 4. Guardrail: new action `request_device_upgrade`

| Check | Rule | Verdict |
|---|---|---|
| 3 params | `{merchant_id, from_device, to_device}`; `from_device` must equal the merchant's current device (fresh DB read) | BLOCK `INVALID_PARAMS` |
| 7b advisor | the advisor, re-run fresh, recommends exactly this `to_device` | BLOCK `OFFER_NOT_ELIGIBLE` |
| 7b gating | no failed/pending settlement, no open ticket or handoff, KYC verified, `device_offer` consent not withdrawn | BLOCK `ISSUE_UNRESOLVED` / `CONSENT_WITHDRAWN` |
| 7b cooling-off | any sales offer (loan, credit line or device) declined in the last `offer_cooling_off_days` | BLOCK `OFFER_COOLING_OFF` |
| 2 kill switch | `disabled_actions: [request_device_upgrade]` | BLOCK `ACTION_DISABLED` |
| 10 consent | always, proactive or not; one yes = one action | NEEDS_CONFIRMATION `CONSENT_REQUIRED` |

Existing reason codes only: a new code would change the `audit_log` CHECK list in the schema.

## 5. Data

- `device_offers` table (new): `id, merchant_id, session_id, trace_id, from_device, to_device, price_json, price_shown_at, consent_at, declined_at, status ('accepted','declined'), ticket_id`. A DB CHECK rejects `accepted` without `price_shown_at` (same idea as the KFS rule).
- `consents.purpose` adds `'device_offer'`: the merchant can stop device marketing (DPDP).
- `sessions.trigger_ref` already supports the dedupe key.

## 6. Work per member

### Shared (PR approved by another member)
- `chaukas/core/models.py`: `ActionType.REQUEST_DEVICE_UPGRADE`, `RequestDeviceUpgradeParams`, `Intent.DEVICE_UPGRADE` (sales track), `HandoffReason.DEVICE_UPGRADE_REQUESTED`, `DeviceAdvice` model, `MerchantContext.device_advice`. All additive.
- `config/policy.yaml`: allow_list, `consent_required`, `proactive_consent_required`, `device_nudge_every_days: 30`.
- `data/schema.sql`: §5. Everyone reseeds after the merge (`python -m data.seed`).
- `CONTRACTS.md`: C1 / C2 / C3 notes.

### Member 1
- `config/device_advisor.yaml` (thresholds + upgrade keywords). ~~`config/device_catalog.yaml`~~ dropped (decision 2: no prices).
- `chaukas/integrations/devices.py`: `advise(merchant_id)`, `request_device_upgrade(...)` (writes `device_offers` + a ticket + `ticket_events`), `record_declined_device_offer`, rollback through `void_ticket`.
- `core/event_watcher.py`: second trigger type `device_upgrade`, with dedupe and the nudge frequency cap.
- `core/plans.py` / `orchestrator.py`: `device_upgrade` intent, the proactive flow, the one-sales-offer-per-session rule.
- `agents/notify.py`, `agents/reply.py`, `config/fallback_replies.yaml` (5 languages), `prompts/intent.v1.txt`, intent keywords.
- Tests: advisor boundaries (avg bill 399/400/401, txn/day 6.9/7.0), flows, dedupe.

### Member 2
- `policy/engine.py`: the checks in §4.
- `data/merchant_fixtures.json`: M021, plus `expected_device_advice` per merchant as a test oracle.
- `tests/test_fairness.py`: the advisor reads only allowed inputs; counterfactuals on name and language.
- Golden: M003 soundbox accepted, M013 blocked (support first), M021 POS, M018 cooling-off. Red-team: wrong `to_device`, another merchant's id, a repeat offer inside the cooling-off window, a proactive offer executed without a yes.

### Member 3
- Notification card: the data numbers, the price, and two buttons (**Details dekhein** / **Abhi nahi**). Then a price card with **Haan / Nahi**. Never merge the two consents into one button.
- Desk: the `DEVICE_UPGRADE_REQUESTED` brief with the ticket timeline.
- Demo scene: scan → M003 popup → Haan → price card → Haan → field-team ticket.

## 7. Decisions (31 Oct, 15:58)

1. **Go:** the team gave an exception to the 4 PM rule; build it now.
2. **No prices shown.** No catalogue, no price card. One consent only: the offer itself asks "shall I send a request to the field team? They will tell you the pricing", and that yes goes to the guardrail. `device_offers.offer_shown_at` records when the offer text was shown (the DB rejects `accepted` without it).
3. **One cooling-off for every sales offer:** a declined loan, credit line or device offer blocks every sales offer for `offer_cooling_off_days`.
4. **M021 is added** as the clean POS merchant.
