"""Prompt rendering + validated LLM calls.

Prompt files (prompts/*.v1.txt) use {variables} filled with str.format(); the JSON O/P SCHEMA block
therefore writes its literal braces doubled ({{ }}).
Context is built with `to_xml()`; every value is XML-escaped so merchant text can never close a tag
and break out of its section (prompt-injection hygiene).

Owner: Member 1 · Contract: prompts/*.v1.txt
"""
from __future__ import annotations

from typing import Any, TypeVar
from xml.sax.saxutils import escape

from pydantic import BaseModel, ValidationError

from chaukas.core import create_logs
from chaukas.db import ROOT
from chaukas.llm.client import LLMResult, LLMUnavailable, complete, extract_json

PROMPTS_DIR = ROOT / "prompts"
T = TypeVar("T", bound=BaseModel)


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def esc(value: Any) -> str:
    return escape(str(value))


def to_xml(tag: str, data: Any) -> str:
    """dict -> nested tags, list -> repeated <item>, scalars -> escaped text. None is skipped."""
    if data is None:
        return ""
    if isinstance(data, dict):
        inner = "".join(to_xml(k, v) for k, v in data.items())
        return f"<{tag}>{inner}</{tag}>"
    if isinstance(data, (list, tuple)):
        inner = "".join(to_xml("item", v) for v in data)
        return f"<{tag}>{inner}</{tag}>"
    if isinstance(data, bool):
        data = str(data).lower()
    return f"<{tag}>{esc(data)}</{tag}>"


class LLMOutputError(Exception):
    """The model answered but the JSON did not validate, even after one repair attempt."""


def run_validated(agent: str, template_file: str, variables: dict[str, str], schema: type[T],
                  replay_key: str | None = None) -> tuple[T, LLMResult]:
    """render -> LLM -> JSON -> Pydantic. One repair retry on a bad output.

    Returns (parsed, aggregated LLMResult). Raises LLMUnavailable or LLMOutputError.
    """
    prompt = load_prompt(template_file).format(**variables)
    total: LLMResult | None = None
    last_error = ""
    for attempt in range(2):
        text_prompt = prompt if attempt == 0 else (
            prompt + f"\n\nYour previous output was invalid ({last_error}). "
                     "Return ONLY the JSON object that matches the O/P SCHEMA."
        )
        try:
            res = complete(agent, text_prompt, replay_key=replay_key)
        except LLMUnavailable as exc:
            create_logs.log_llm_call(agent, template_file, attempt + 1, text_prompt, error=f"unavailable: {exc}")
            raise
        create_logs.log_llm_call(agent, template_file, attempt + 1, text_prompt, output=res.text, model=res.model,
                                 source=res.source, latency_ms=res.latency_ms, tokens_in=res.tokens_in,
                                 tokens_out=res.tokens_out, cost_inr=res.cost_inr)
        if total is None:
            total = res
        else:
            total = total.model_copy(update={
                "text": res.text,
                "tokens_in": total.tokens_in + res.tokens_in,
                "tokens_out": total.tokens_out + res.tokens_out,
                "cost_inr": total.cost_inr + res.cost_inr,
                "latency_ms": total.latency_ms + res.latency_ms,
            })
        try:
            return schema.model_validate(extract_json(res.text)), total
        except (ValueError, ValidationError) as exc:
            last_error = str(exc).replace("\n", " ")[:160]
    raise LLMOutputError(last_error)


__all__ = ["to_xml", "esc", "run_validated", "LLMOutputError", "LLMUnavailable"]
