# Member 3 — Interface + Privacy + Demo

> **Project:** Chaukas (चौकस) · **Team:** Enver AI · **Track 3 — Autonomous AI Teammates**
> **Your role:** Make it usable, make it private, and make it presentable.
> **Full context:** read `CHAUKAS_PROBLEM_STATEMENT.md` + `CHAUKAS_SYSTEM_DESIGN.md` once before starting.

---

## 1. The problem (30-second version)

Chaukas is an AI teammate that acts for merchants — fixes settlements, raises tickets, offers consented loans — in their own language, and checks itself before touching money. It works in two modes: **merchant-facing** (the merchant talks to it) and **teammate copilot** (a Paytm support agent uses it). You build the faces people actually see, the privacy layer that protects merchant data, and the demo that sells it all.

---

## 2. Your task

Three things:
1. **Interface** — merchant chat + agent-desk copilot view.
2. **Privacy / PII** — the masking, tokenising and scrubbing layer (finance-grade; the same model covers healthcare too).
3. **Demo** — the video, the deck update, and (if time) the Hindi voice loop.

**You own these files:**
```
channel/chat.py           # merchant text in/out
channel/voice.py          # [if time] Hindi streaming ASR + TTS
privacy/pii.py            # detect / mask / tokenise / encrypt / decrypt
privacy/scrub.py          # scrub PII from logs + traces
ui/                       # merchant chat view + agent-desk copilot view
(demo video + updated pitch deck)
```

---

## 3. Privacy / PII — how it works (do this first, it's foundational)

Chaukas touches settlements, loan eligibility and merchant identity — regulated financial data. PII protection is a first-class requirement. **Everyone downstream depends on your masking**, so build this early.

**PII fields:** account_no, vpa/upi, phone, pan, aadhaar, name, ifsc.

**Four controls at four points (system design A8):**
| Point | What you do |
|-------|-------------|
| Ingestion | detect PII at entry, mask/tokenise it |
| Before LLM call | model sees tokenised refs, never raw identity |
| Storage / cache | encrypt PII at rest |
| Logs / trace / audit | `scrub()` — only masked values ever persisted |

**`pii.py` functions:** `detect`, `mask` (→ `XXXXXX3421`), `tokenise` (reversible ref), `detokenise` (only the Action Agent, only when needed), `encrypt`/`decrypt`.
**`scrub.py`:** recursively mask PII in any object before it reaches logs/trace/audit.

**Per-agent scope (least privilege):** Intent Agent sees masked text only; Context Agent sees tokenised refs; Guardrail sees amounts not identity; Action Agent detokenises only the one field a tool needs; Handoff sees masked summary. Enforce this.

---

## 4. Interface — how it works

**Merchant chat (`chat.py` + ui):** a simple text chat where a merchant types (or speaks) their issue and sees Chaukas resolve it. Show the reply in the merchant's language. Keep it clean — judges should follow the conversation at a glance.

**Agent-desk copilot view:** the *second mode* — what a Paytm support agent sees. Show the pre-fetched context, the drafted resolution, a one-click "execute", and the **handoff brief** (what was asked, verified, done, refused + why, confidence, the one decision needed). This proves "works alongside human teams" — a lot of teams will skip it, so it's a differentiator.

**Show the guardrail visibly.** When Member 2's guardrail blocks or asks for confirmation, surface it in the UI (e.g. a "⚠ needs confirmation: ₹1,00,000 over limit" state). This makes the demo's wow-moment visible.

---

## 5. Voice (only after the text loop works)

`voice.py`: streaming ASR (speech→text) in, TTS (text→speech) out, Hindi first. **Streaming is mandatory** — non-streaming means 5+ second waits that kill the demo. Keep a text fallback so a mic failure on stage doesn't break the demo. This is the *last* thing you build; a working text demo beats a half-working voice demo.

---

## 6. Demo video + deck update

- **Demo video:** record the settlement-fix flow end-to-end, including the guardrail blocking an over-limit action and the consented loan offer. Keep it tight. Narrate the approach, not just the screen.
- **Deck update:** the Stage-1 deck (`Chaukas_Pitch_Deck.pptx`) described a roadmap. Update the roadmap slide to reflect what's actually built for the finals — honestly, no overclaiming.

---

## 7. Build order (your part)

1. `privacy/pii.py` + `privacy/scrub.py` — foundational; unit-test mask/tokenise/scrub first.
2. `channel/chat.py` + a minimal merchant chat UI (wire to Member 1's loop once it runs with stubs).
3. Agent-desk copilot view + visible guardrail states.
4. Demo video + deck update.
5. `channel/voice.py` (Hindi) — last, only if steps 1–4 are solid.

---

## 8. Dependencies & handoffs

- **You → everyone:** `privacy/` lands first; Members 1 & 2 import your mask/tokenise/scrub. Agree the function signatures early.
- **Member 1 → you:** the chat UI wires into their orchestrator loop; the agent-desk view renders their `HandoffBrief`. Agree its shape.
- **Member 2 → you:** your PII-scrub functions power their PII-leak test; the guardrail states you surface in the UI come from their `Decision`.

---

## 9. Definition of done

- [ ] `pii.py` masks/tokenises all PII fields; `scrub()` cleans any object.
- [ ] No raw PII appears in logs, traces, prompts, or the UI (verified by Member 2's test).
- [ ] Merchant chat shows a full settlement-fix conversation end-to-end.
- [ ] Agent-desk view shows context + handoff brief + a visible guardrail state.
- [ ] Demo video recorded; deck roadmap slide updated honestly.
- [ ] (Stretch) Hindi voice loop works with a text fallback.
- [ ] You can explain the four-point PII model on stage.

---

## 10. Interview / viva prep (judges will ask)

- How do you keep merchant financial data private? (four controls: mask at ingestion, tokenise to model, encrypt at rest, scrub logs)
- Does the LLM ever see raw account numbers? (no — tokenised references only)
- How does this generalise to healthcare? (same mask/encrypt/scope model applies to PHI)
- What makes this "work alongside human teams"? (the agent-desk copilot mode + structured handoff brief)
- Why voice last? (reliability — a working text demo beats a broken voice demo)
