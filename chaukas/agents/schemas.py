"""Pydantic models for LLM agent outputs (the `O/P SCHEMA` block of each prompt file).

Each prompt asks for {"thought_process": ..., "<agent>_result": {...}}. The reply is validated
against these models before any other agent sees it. `thought_process` is for tracing only: it is
never shown to the merchant and never stored unscrubbed.

Owner: Member 1 · Contract: prompts/*.v1.txt
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from chaukas.core.models import Intent, Track, Urgency


class _Base(BaseModel):
    thought_process: str = Field(default="", max_length=1500)


class IntentResult(BaseModel):
    intent: Intent
    lang: str = "hi-IN"
    urgency: Urgency = Urgency.MED
    track: Track = Track.SUPPORT
    confidence: float = Field(ge=0.0, le=1.0)

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
