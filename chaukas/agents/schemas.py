"""Pydantic models for LLM agent outputs (the `O/P SCHEMA` block of each prompt file).

Each prompt asks for {"thought_process": ..., "<agent>_result": {...}}. The reply is validated
against these models before any other agent sees it. `thought_process` is for tracing only: it is
never shown to the merchant and never stored unscrubbed.

Owner: Member 1 · Contract: prompts/*.v1.txt
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from chaukas.core.models import Intent, Track, Urgency
from chaukas.integrations._common import load_config


class _Base(BaseModel):
    thought_process: str = Field(default="", max_length=1500)


def language_codes() -> list[str]:
    """The closed list of language codes (config/languages.yaml `detect`)."""
    return list(load_config("languages")["detect"])


def normalize_lang(value: object) -> str:
    """Map the model's answer onto `detect`: exact code, alias, then base language ('gu' -> 'gu-IN').
    A language we do not support (e.g. 'ta-IN') -> `unsupported` (English), never Hindi; no answer at all ->
    `default`. A wrong language code never throws away a correct intent."""
    cfg = load_config("languages")
    codes = list(cfg["detect"])
    key = str(value or "").strip().lower().replace("_", "-")
    if not key:
        return cfg["default"]
    by_lower = {c.lower(): c for c in codes}
    aliases = {str(k).lower(): v for k, v in (cfg.get("aliases") or {}).items()}
    if key in by_lower:
        return by_lower[key]
    if key in aliases:
        return aliases[key]
    base = key.split("-")[0]
    return next((c for c in codes if c.endswith("-IN") and c.split("-")[0].lower() == base), cfg["unsupported"])


class IntentResult(BaseModel):
    intent: Intent
    lang: str = "hi-IN"  # one of config/languages.yaml `detect` (normalised below)
    urgency: Urgency = Urgency.MED
    track: Track = Track.SUPPORT
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("lang", mode="before")
    @classmethod
    def _lang_in_enum(cls, v):
        return normalize_lang(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_conf(cls, v):  # models sometimes answer "0.9" or 90
        v = float(v)
        return v / 100 if v > 1 else v


class IntentOutput(_Base):
    intent_result: IntentResult


class ReplyResult(BaseModel):
    reply: str = Field(min_length=1, max_length=1200)


class ReplyOutput(_Base):
    reply_result: ReplyResult


class HandoffResult(BaseModel):
    asked: str = Field(min_length=1, max_length=300)
    decision_needed: str = Field(min_length=1, max_length=400)


class HandoffOutput(_Base):
    handoff_result: HandoffResult
