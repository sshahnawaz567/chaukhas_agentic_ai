"""Intent & Language agent: 1 LLM call -> {intent, lang, urgency, track, confidence}.
Keyword fallback when the LLM is unavailable. Sees masked text only.

Owner: Member 1 · Contract: CONTRACTS C1
"""
from __future__ import annotations

import re

from chaukas.agents.schemas import IntentOutput, IntentResult
from chaukas.core.models import ConversationState, Intent, Track, Urgency
from chaukas.integrations._common import load_config
from chaukas.llm.client import LLMResult, LLMUnavailable
from chaukas.llm.prompt import LLMOutputError, esc, run_validated, to_xml

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_GUJARATI = re.compile(r"[઀-૿]")

# Keyword fallback. Latin Hinglish + Devanagari. Deliberately small and conservative.
_CONFIRM = re.compile(r"\b(haan|han|haa|ha|yes|yep|ok|okay|sure|theek hai|thik hai|bhej\s*do|bhejo|kar\s*do|ji haan)\b|हाँ|हां|भेज दो|भेजो|ठीक है|कर दो", re.I)
_DENY = re.compile(r"\b(nahi|nahin|nope|no|mat|cancel|rehne do)\b|नहीं|नही|मत|रहने दो", re.I)
_HUMAN = re.compile(r"\b(insaan|insan|human|real person|manager|agent se|shikayat|shikaayat|complaint|grievance|kisi se baat)\b|इंसान|इन्सान|शिकायत|मैनेजर|किसी से बात", re.I)
_REFUND = re.compile(r"\b(refund|refund karna|customer ko wapas)\b|रिफंड", re.I)
_LOAN = re.compile(r"\b(loan|udhaar|udhar|credit|karz|karj)\b|लोन|उधार|कर्ज", re.I)
_INSURANCE = re.compile(r"\b(insurance|bima|beema)\b", re.I)
_DEVICE = re.compile(r"\b(soundbox|sound box|qr|pos|speaker|device|machine|battery)\b|साउंडबॉक्स|क्यूआर|स्पीकर|मशीन", re.I)
_SETTLEMENT = re.compile(r"\b(settlement|paisa|paise|payment|payout|nahi aaya|nahin aaya|transfer|bheja)\b|पैसा|पैसे|भुगतान|सेटलमेंट|नहीं आया|नही आया", re.I)
_URGENT = re.compile(r"\b(jaldi|urgent|turant|abhi|asap|2 din|do din)\b|जल्दी|तुरंत|अभी", re.I)
_HINGLISH_HINTS = re.compile(r"\b(mera|meri|hai|nahi|nahin|kya|bhai|paisa|paise|aaya|bhej|bhejo|karo|karna|mujhe|"
                             r"hamara|abhi|din|haan|haa|theek|thik|milega|chahiye|kab|kyun)\b", re.I)


def _keyword_lang(text: str) -> str:
    """hi-IN = Devanagari Hindi; gu-IN = Gujarati; hi-Latn = Hinglish in Latin letters; anything else English
    (the supported list is config/languages.yaml `detect`)."""
    if _DEVANAGARI.search(text):
        return "hi-IN"
    if _GUJARATI.search(text):
        return "gu-IN"
    return "hi-Latn" if _HINGLISH_HINTS.search(text) else "en-IN"


def injection_signals(text: str) -> list[str]:
    """Names of the prompt-injection patterns (config/injection.yaml) found in the message. Deterministic:
    runs before any LLM, so a model that would obey the injection never gets to word the outcome."""
    patterns = load_config("injection").get("patterns") or {}
    return [name for name, rx in patterns.items() if re.search(rx, text or "", re.I)]


def keyword_classify(text: str, pending: bool) -> IntentResult:
    """Deterministic fallback. Confidence is 0.75 on a clear single-category hit, 0.3 on unknown."""
    lang = _keyword_lang(text)
    short = len(text.split()) <= 6
    if pending and short:
        if _DENY.search(text):
            return IntentResult(intent=Intent.DENY, lang=lang, urgency=Urgency.LOW, track=Track.SUPPORT, confidence=0.8)
        if _CONFIRM.search(text):
            return IntentResult(intent=Intent.CONFIRM, lang=lang, urgency=Urgency.LOW, track=Track.SUPPORT, confidence=0.8)

    urgency = Urgency.HIGH if _URGENT.search(text) else Urgency.MED
    for rx, intent, track in (
        (_HUMAN, Intent.HUMAN_REQUEST, Track.SUPPORT),
        (_REFUND, Intent.REFUND_REQUEST, Track.SUPPORT),
        (_INSURANCE, Intent.INSURANCE_INQUIRY, Track.SALES),
        (_LOAN, Intent.LOAN_INQUIRY, Track.SALES),
        (_DEVICE, Intent.DEVICE_ISSUE, Track.SUPPORT),
        (_SETTLEMENT, Intent.SETTLEMENT_DELAY, Track.SUPPORT),
    ):
        if rx.search(text):
            return IntentResult(intent=intent, lang=lang, urgency=urgency, track=track, confidence=0.75)
    return IntentResult(intent=Intent.UNKNOWN, lang=lang, urgency=Urgency.LOW, track=Track.SUPPORT, confidence=0.3)


def _context_xml(state: ConversationState, pending: bool) -> str:
    recent = [{"role": t.role, "text": t.text_masked} for t in state.history[-3:]]
    return to_xml("intent_context", {"pending_request": pending, "recent_turns": recent or None})


def classify(state: ConversationState, pending: bool) -> tuple[IntentResult, LLMResult | None, str]:
    """Returns (result, llm_result_or_None, source) with source in {"llm", "keyword"}."""
    variables = {
        "context": _context_xml(state, pending),
        "user_question": esc(state.message_masked),
    }
    replay_key = f"intent|{state.merchant_id}|{state.message_masked}|{pending}"
    try:
        out, llm = run_validated("intent", "intent.v1.txt", variables, IntentOutput, replay_key=replay_key)
        result = out.intent_result
        source = "llm"
    except (LLMUnavailable, LLMOutputError):
        return keyword_classify(state.message_masked, pending), None, "keyword"

    # code-level guard: the model may not return confirm/deny when nothing is pending
    if not pending and result.intent in (Intent.CONFIRM, Intent.DENY):
        result = result.model_copy(update={"intent": Intent.UNKNOWN, "confidence": min(result.confidence, 0.3)})
    return result, llm, source
