# Backend changes for Member 1

> **From:** Member 3 (UI) · **To:** Member 1 (Agent Core + API) · **Date:** 31 Oct 2026
> **Status:** The UI is already connected to the real backend and already handles every change below. Each change is **additive**: until you ship it, the UI behaves exactly as it does today. Nothing breaks if you ship only some of them.

| # | Change | Priority | Files | Shared file? |
|---|--------|----------|-------|--------------|
| 1 | Loan accepted → follow-up brief on the agent desk | P0 (team asked for it) | `core/orchestrator.py`, `integrations/lending.py`, `core/models.py` | `models.py`: PR needs Member 2's approval |
| 2 | Structured KFS in `pending_confirmation` | P1 | `core/orchestrator.py` | No |
| 3 | `openai` package must be installed on every demo laptop | P0, setup only | none | No |

---

## Change 1: loan accepted → follow-up brief

### What

When the merchant says **haan** to a loan offer and the offer is accepted, create a handoff so the loan team sees all the loan details on the agent desk. This works like the payment flow, with one difference: it is a **follow-up, not an approval gate**.

- The offer is already accepted with `ALLOW CONFIRMED_BY_MERCHANT`. The guardrail, `policy.yaml` and the decision do not change.
- Chaukas never moves loan money; the lender does.
- The agent reads the brief, follows up, and clicks **Mark followed up**.
- **abhi nahi** (decline) creates **no** handoff.

### Models (additive, `core/models.py`)

```python
class HandoffReason(str, Enum):
    ...
    LOAN_ACCEPTED = "LOAN_ACCEPTED"  # merchant accepted an offer: back-office follow-up, not an approval


class LoanFollowUp(BaseModel):  # what the loan team needs; values from the offers row, never from the LLM
    offer_id: str
    amount: int
    lender_name: str
    apr_pct: float
    processing_fee_inr: int
    tenure_months: int
    total_repayable_inr: int
    grievance_contact: str
    kfs_shown_at: str | None
    consent_at: str | None
    consent_audit_id: int | None  # the ALLOW CONFIRMED_BY_MERCHANT audit row


class HandoffBrief(BaseModel):
    ...
    loan: LoanFollowUp | None = None  # ADDITIVE: set only on a LOAN_ACCEPTED brief
```

`handoffs.reason_code` has no CHECK constraint, so `schema.sql` does not change.

### Read helper (`integrations/lending.py`)

```python
def get_offer(offer_id: str) -> dict | None:
    """One offers row with kfs_json parsed. Read-only."""
    # SELECT id, amount, lender_name, kfs_json, kfs_shown_at, consent_at FROM offers WHERE id = ?
```

### Orchestrator (`core/orchestrator.py`)

**Hook:** `_resume()`, in the branch where `_run_allowed(...)` succeeded and `step.action_type == create_offer` (right after `_grant_consent(s, "loan_offer", kfs_shown=True)`).

> ⚠️ **Do not set `s.handoff` in `_resume()`.** `reply_agent.generate(s)` reads `state.handoff`:
> - `facts["handoff"] = True` makes the reply say "connecting you to the team".
> - `_signature()` puts `bool(state.handoff)` into the **replay key**, so the recorded Sarvam reply for this turn would miss and fall back to the template.
>
> Build the brief in `_resume()`, keep it on the `_Turn` object (your own class, not a shared model), and attach it in `_finish()` **after** the reply is generated.

```python
# _resume(), create_offer success branch
if step.action_type == ActionType.CREATE_OFFER.value:
    _grant_consent(s, "loan_offer", kfs_shown=True)
    turn.loan_brief = _loan_brief(s, step, decision)   # attached in _finish(), after the reply


def _loan_brief(s: ConversationState, step: PlannedStep, decision: Decision) -> HandoffBrief | None:
    done = next((a for a in s.completed if a.step_no == step.step_no and a.status == "success"), None)
    offer = lending.get_offer(done.ref_id) if done and done.ref_id else None
    if offer is None:
        return None
    kfs = offer["kfs"]
    return HandoffBrief(
        asked=f"Merchant accepted a ₹{offer['amount']:,} business loan offer",
        verified=["Key Fact Statement shown before consent",
                  f"Consent recorded (CONFIRMED_BY_MERCHANT, audit #{decision.audit_id})"],
        done=[f"Offer {offer['id']} accepted"],
        refused=[], reason_code=HandoffReason.LOAN_ACCEPTED.value, confidence=1.0,
        decision_needed=f"Follow up with the lender on {offer['id']} and confirm next steps with the merchant",
        suggested_step=None,
        loan=LoanFollowUp(offer_id=offer["id"], amount=offer["amount"], lender_name=offer["lender_name"],
                          apr_pct=kfs["apr_pct"], processing_fee_inr=kfs["processing_fee_inr"],
                          tenure_months=kfs["tenure_months"], total_repayable_inr=kfs["total_repayable_inr"],
                          grievance_contact=kfs["grievance_contact"], kfs_shown_at=offer["kfs_shown_at"],
                          consent_at=offer["consent_at"], consent_audit_id=decision.audit_id),
    )


# _finish(), after `text, llm, source = reply_agent.generate(s)` and before building TurnResponse
if getattr(turn, "loan_brief", None) is not None:
    t = time.perf_counter()
    s.handoff = turn.loan_brief
    s.handoff_id = handoff.save(s, s.handoff)
    turn.span("handoff", "reason LOAN_ACCEPTED", f"{s.handoff_id}: {s.handoff.decision_needed}", t)
```

Rules:
- The brief is deterministic. Do not call the LLM.
- **`s.status` stays `COMPLETED`**, not `HANDED_OFF`. The merchant's request is done; this is back-office work.
- Every value comes from the `offers` row and the decision, never from the merchant's message. Amounts are `int`.
- The brief holds no PII (offer id, amounts, lender name, timestamps). Still route `asked` and `decision_needed` through `m2_shim.mask_text` like `handoff.build()` does.
- The span order is fine as is: the UI shows spans in the order they arrive.
- The reply may stay as it is. If you want, add one line: "हमारी लोन टीम आपसे संपर्क करेगी।" Re-record the reply if you change the wording.

### Closing it on the desk

No change. The UI sends this, and it already works with today's `api/desk.py`:

```json
POST /api/handoffs/{id}/resolve
{"staff_id": "STAFF-042", "decision": "loan follow-up done for OFF-xxxxx", "execute_suggested": false}
```

### Tests (`tests/`)

1. M001 Scene 1 → haan: `GET /api/handoffs` lists one `LOAN_ACCEPTED` handoff. Its `brief.loan.offer_id` equals the `create_offer` action's `ref_id`, and `brief.loan.total_repayable_inr` equals `offers.kfs_json`.
2. The confirm `TurnResponse` has `status == "completed"` and `handoff.reason_code == "LOAN_ACCEPTED"`.
3. The reply text is identical with and without this change (replay key unchanged).
4. M001 → abhi nahi: no handoff is created.
5. Resolve with `execute_suggested: false` → handoff `resolved`, no `executions` row added.
6. The Scene 2 payout handoff is unaffected.

### What the UI already does with it

- Chat: shows "Brief sent to the loan team · HO-xxxxx" (from `TurnResponse.handoff` + the `handoff` span).
- Agent desk: shows a "Loan details — as shown to the merchant" table (offer, lender, amount, APR, fee, tenure, total repayable, grievance, KFS-shown time, consent time + audit #). The button reads **Mark followed up** and executes nothing.
- The newest handoff sits on top of the queue, so after Scene 2 the payout handoff is still first for Scene 3.
- To preview it now: run the UI with `VITE_USE_MOCK=true` and open handoff `HO-10022`.

---

## Change 2: structured KFS in `pending_confirmation` (NOTES_FOR_TEAM B1)

### Why

RBI Digital Lending: the merchant must see the Key Fact Statement **before** Haan/Nahi. Today the KFS reaches the UI only inside the reply text, so the loan card shows just the amount. With structured fields, the card shows the full KFS table next to the buttons.

### Change (`core/orchestrator.py`, `_finish()`)

```python
if s.pending_step is not None:
    pending_confirmation = {...existing keys...}
    if (s.pending_meta or {}).get("kind") == "consent" and s.pending_step.action_type == ActionType.CREATE_OFFER.value:
        p = s.pending_step.params
        pending_confirmation["kfs"] = lending.build_kfs(p["merchant_id"], p["amount"]).model_dump()
```

- Use `build_kfs` because `reply.py` and `action.py` already use it, so the card, the reply text and the `offers.kfs_json` row always match.
- `TurnResponse.pending_confirmation` is a `dict`, so `models.py` does not change. Document the key in CONTRACTS C5 (additive).
- Test: the Scene 1 turn has `pending_confirmation.kfs.total_repayable_inr == 59500` with the current `config/lender_sim.yaml`.

---

## Change 3: install `openai` (setup only)

`chaukas/llm/client.py` calls **Sarvam** (and Gemini) through the OpenAI-compatible Python SDK: `from openai import OpenAI` with `base_url: https://api.sarvam.ai/v1` from `config/models.yaml`. The package sends nothing to OpenAI. It is only the HTTP client.

Without it, `CHAUKAS_REPLAY_MODE=off` crashes every turn with `ModuleNotFoundError: No module named 'openai'`, because `_client()` imports it before checking for a key. `replay` mode works without it.

Please keep `openai` in `requirements.txt` and make sure it is installed on the demo laptop: `pip install -r requirements.txt`.

Optional hardening (your call): in `_client()`, return `None` when the API key is empty **before** `from openai import OpenAI`. Then a laptop with no keys and no package falls back cleanly instead of crashing.

---

## How to check it end to end

```bash
python -m data.seed && uvicorn chaukas.main:app --port 8000   # repo root
cd ui && npm run dev                                          # http://localhost:8080
```

1. Merchant tab → **M001** → send the Hindi chip → the loan card shows the full KFS table (change 2).
2. Click **हाँ, आगे बढ़ें** → the chat shows "Brief sent to the loan team · HO-xxxxx" (change 1).
3. **M002** → send the Hinglish chip (Scene 2).
4. **Agent desk** → the payout handoff is on top (Scene 3 unchanged). The loan brief is below it with the loan table → **Mark followed up**.
