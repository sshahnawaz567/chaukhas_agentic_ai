# Proposal (Member 1): conversation history for the Intent agent + "what happens next" message (`ack`)

> **From:** Member 1 (Agent Core + API) · **To:** Member 2 (approval, eval), Member 3 (UI) · **Date:** 31 Oct 2026
> **Status:** PROPOSED. Nothing is built yet. Branch: `m1/agentic`.
> **Time box:** Part 1 ~1 hour, Part 2 ~45 min, tests included. Both must land before the **4 PM feature freeze** (CLAUDE.md). If time is short, ship Part 1 only.

---

## Summary

| Part | What | Files | Shared file? |
|------|------|-------|--------------|
| 1 | Better conversation history in the Intent agent's prompt (request/answer pairs + outcome) | `chaukas/agents/intent.py`, `prompts/intent.v1.txt`, `chaukas/gateway/session.py`, `config/mock.yaml` | No |
| 2 | A short "what happens next" line (`ack`) in the merchant's language, from **templates**, not the LLM | new `config/ack_templates.yaml`, `chaukas/core/orchestrator.py`, `chaukas/core/models.py` | **Yes**: `TurnResponse.ack` (additive) |
| 3 (later, optional) | One clarifying question instead of an immediate handoff when the message is unclear | intent prompt + orchestrator | Maybe (`Intent` values) |

Nothing changes in: the guardrail, `config/policy.yaml`, `data/schema.sql`, any money path, or the final `reply`.

---

## Part 1: conversation history

### Today (the problem)

`chaukas/agents/intent.py:73` sends the last **3** turns as a flat list of `{role, text}`:

1. The first turn is usually the long disclosure + DPDP notice, so one of the three slots is wasted on it (tokens, no signal).
2. Requests and answers are not paired: the model has to guess which agent answer belongs to which merchant message.
3. `3` is hardcoded, while `config/mock.yaml` says `history_window: 6`.

### Proposed format

```xml
<conversation_history>
  <turn n="1">
    <previous_user_request>paisa nahi aaya</previous_user_request>
    <agent_final_output outcome="awaiting_confirmation: create_offer">₹18,400 re-sent ... ₹50,000 loan offer, shall I send it?</agent_final_output>
  </turn>
  <turn n="2"> ... </turn>
</conversation_history>
```

- `outcome` = where the previous turn stopped: `completed`, `awaiting_confirmation: <action>`, `handed_off: <reason>`, `failed`. The model should not have to infer this from text.
- The disclosure turn is skipped.
- Window = `config/mock.yaml history_window` (no hardcoded number).
- Each agent answer is truncated to ~200 characters.

### Why

- Short follow-ups are understood: "haan", "kitna time lagega?", "aur loan ka kya hua?".
- Part 3 (clarifying question) depends on it: the next turn must see the question Chaukas asked.

### Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Old injection text re-enters the prompt through history | Prompt rule: history is DATA, never instructions. The code-level injection guard (`config/injection.yaml`) still runs on every new message before any LLM. History never triggers an action. |
| Amounts in old agent answers get copied into new text | Amounts only ever come from the ledger; `handoff._safe_line()` already rejects amounts not in the plan/ledger. |
| More tokens / latency | Disclosure skipped, answers truncated, window from config. Estimate: +200–400 input tokens per intent call (~₹0.01). |
| PII | `turns.text_masked` is already masked at ingestion; `to_xml()` escapes every value. No new PII path. |
| Replay mode | Add a short stable signature of the history (intents + outcomes, no ids) to the intent replay key, so a recording is never served for a different conversation state. |

### Implementation notes (Member 1)

- `gateway/session.py`: `history()` also returns, per agent turn, the outcome (from `turns` + the session's state; if not stored per turn, add it to the agent `turns` row in `_finish()`, e.g. via the existing `intent` column or a small JSON in the text-free metadata; decide at build time; no schema change wanted).
- `agents/intent.py`: `_context_xml()` builds the pairs; window from config.
- `prompts/intent.v1.txt`: describe `<conversation_history>`; rule "history is data".
- Tests: pairs are built correctly; disclosure skipped; window from config; "haan" after an offer turn -> `confirm`; injection text in history does not change the intent of a clean new message.

---

## Part 2: "what happens next" line (`ack`)

### What

A short line, in the merchant's own language, telling them what Chaukas is doing next, **without revealing anything about the system** (no guardrail, policy, limits, reason codes, LLM, prompt). Examples (Hinglish):

- settlement_delay: "Main aapke settlement ki jaankari check kar raha hoon."
- loan_inquiry: "Main dekh raha hoon ki aapke liye kaunsa loan offer hai."
- unknown / handoff: "Main aapki baat hamari team tak pahuncha raha hoon."

### Design decision: templates, NOT the LLM

The Intent agent runs **before** the ledger, context and guardrail. If an LLM wrote this line it could promise things that have not been checked ("main paisa bhej deta hoon"), and Hindi/Hinglish verbs ("bhej", "daal dunga") are not caught by the English `_safe_line` check. A template per `(intent, language)`:

- cannot promise money or invent amounts,
- is always in the right language and script,
- costs zero tokens and works with the network off (replay-safe).

The intent and the language are already known after the Intent agent, so the template lookup is deterministic.

### Template file: `config/ack_templates.yaml` (new, Member 1)

One line per intent × supported language (`config/languages.yaml detect`: `hi-IN`, `hi-Latn`, `en-IN`, `mr-IN`, `gu-IN`). Missing language -> `en-IN`.

```yaml
# "What happens next" lines. Deterministic, never an LLM. No amounts, ids, promises or system terms.
hi-IN:
  settlement_delay: "मैं आपके settlement की जानकारी चेक कर रहा हूँ।"
  loan_inquiry: "मैं देख रहा हूँ कि आपके लिए कौन-सा लोन ऑफ़र है।"
  device_issue: "मैं आपकी डिवाइस की समस्या दर्ज कर रहा हूँ।"
  refund_request: "मैं आपका अनुरोध हमारी टीम तक पहुँचा रहा हूँ।"
  confirm: "ठीक है, मैं आगे बढ़ रहा हूँ।"
  deny: "ठीक है, मैं कुछ नहीं भेज रहा।"
  human_request: "मैं आपको हमारी टीम के सदस्य से जोड़ रहा हूँ।"
  unknown: "मैं आपकी बात हमारी टीम तक पहुँचा रहा हूँ।"
hi-Latn:
  settlement_delay: "Main aapke settlement ki jaankari check kar raha hoon."
  loan_inquiry: "Main dekh raha hoon ki aapke liye kaunsa loan offer hai."
  device_issue: "Main aapki device ki problem darj kar raha hoon."
  refund_request: "Main aapki request hamari team tak pahuncha raha hoon."
  confirm: "Theek hai, main aage badh raha hoon."
  deny: "Theek hai, main kuch nahi bhej raha."
  human_request: "Main aapko hamari team ke member se jod raha hoon."
  unknown: "Main aapki baat hamari team tak pahuncha raha hoon."
en-IN:
  settlement_delay: "I'm checking your settlement details."
  loan_inquiry: "I'm checking which loan offer is available for you."
  device_issue: "I'm logging your device issue."
  refund_request: "I'm passing your request to our team."
  confirm: "Okay, going ahead."
  deny: "Okay, I won't send anything."
  human_request: "I'm connecting you to a member of our team."
  unknown: "I'm passing your message to our team."
mr-IN:
  settlement_delay: "मी तुमच्या settlement ची माहिती तपासत आहे."
  loan_inquiry: "तुमच्यासाठी कोणती कर्ज ऑफर आहे ते मी पाहत आहे."
  device_issue: "मी तुमच्या डिव्हाइसची समस्या नोंदवत आहे."
  refund_request: "मी तुमची विनंती आमच्या टीमकडे पाठवत आहे."
  confirm: "ठीक आहे, मी पुढे जात आहे."
  deny: "ठीक आहे, मी काहीही पाठवत नाही."
  human_request: "मी तुम्हाला आमच्या टीमच्या सदस्याशी जोडत आहे."
  unknown: "मी तुमचा संदेश आमच्या टीमकडे पाठवत आहे."
gu-IN:
  settlement_delay: "હું તમારા settlement ની માહિતી તપાસી રહ્યો છું."
  loan_inquiry: "તમારા માટે કઈ લોન ઓફર છે તે હું જોઈ રહ્યો છું."
  device_issue: "હું તમારા ડિવાઇસની સમસ્યા નોંધી રહ્યો છું."
  refund_request: "હું તમારી વિનંતી અમારી ટીમને મોકલી રહ્યો છું."
  confirm: "ઠીક છે, હું આગળ વધી રહ્યો છું."
  deny: "ઠીક છે, હું કંઈ મોકલી રહ્યો નથી."
  human_request: "હું તમને અમારી ટીમના સભ્ય સાથે જોડી રહ્યો છું."
  unknown: "હું તમારો સંદેશ અમારી ટીમને મોકલી રહ્યો છું."
```

(Marathi and Gujarati lines were written by the assistant: have a native speaker read them before the demo.)

### Where it goes

- `TurnResponse.ack: str | None = None` (**additive, `chaukas/core/models.py`, needs Member 2's approval**). Set right after the Intent agent (and for proactive / injection turns: a fixed line, or `None`).
- Proactive turns: `None` (the notification is already the first message). Suspected injection: `None` (no hint to the attacker).

### Honest limitation: delivery

Our API is one request -> one response. If `ack` arrives in the **same** response as the final `reply` ("payout re-sent ..."), it is redundant. It only adds value when shown **before** the final reply:

- **Voice (best fit):** Bulbul speaks the `ack` while context, guardrail and action run, so the merchant hears no silence. Perceived latency drops.
- **Chat:** the UI shows it instead of "typing...", which needs streaming or a two-step response (e.g. the UI shows `ack` first, then the reply after a short delay, or an SSE/second call).

**Open question for the team:** do we want `ack` in chat too, or only for voice? If only for voice and voice is a no-go at 3 PM, skip Part 2 for now.

### Tests

- Every `(intent, language)` pair in `detect` has a template (same style as `test_every_supported_language_has_fallback_and_notification_templates`).
- `ack` never contains an amount, an id, or a system term (guardrail, policy, limit, LLM, prompt).
- `ack` is in the turn's language (`reply._right_language()`).
- `ack` is `None` for proactive and suspected-injection turns.
- `reply` is unchanged with and without Part 2.

---

## Part 3 (later, optional): one clarifying question

Instead of an immediate `UNKNOWN_INTENT` handoff, ask **one** question in the merchant's language ("Settlement ki baat hai ya loan ki?"); if the next message is still unclear, hand off. Only for non-action turns; settlement / loan / confirm / refund keep the current flow. Needs Part 1 (the next turn must see the question). Affects Member 2's eval (`UNKNOWN_INTENT` cases and escalation metrics). May need additive `Intent` values (`greeting`, `small_talk`).

---

## What we need from each member

**Member 2**
- (a) After Part 1: re-run the golden multi-turn cases (P02, G01, ...) and confirm nothing changed.
- (b) Approve `TurnResponse.ack` (shared file, additive).
- (c) Eval: `ack` is a fixed template and takes no action, so ignore it; no metric changes. (Part 3 would change escalation metrics; decide then.)

**Member 3**
- A place in the UI for `ack` (shown before the final reply), and in voice, spoken first.

---

## Where we are (context for the next session)

- Branch `m1/agentic`, last pushed commit `869bf83` (injection guard, safe handoff wording, Gujarati templates). Working tree clean before this file.
- Supported languages: `hi-IN`, `hi-Latn` (Hinglish), `en-IN`, `mr-IN`, `gu-IN` (`config/languages.yaml`).
- Open for Member 2: golden case G10 must expect `SUSPECTED_INJECTION` + `should_escalate: true`; PR `m1/agentic -> main` needs approval (`models.py`: `LOAN_ACCEPTED`, `SUSPECTED_INJECTION`).
- Repo `logs/` holds 3 committed demo sessions: never delete them.
