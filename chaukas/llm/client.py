"""One OpenAI-compatible client. Routing: Sarvam-30B core, Gemini Flash fallback.
Returns text + token counts + cost for trace spans.

Everything an LLM sees has already been masked at ingestion; as defence in depth `complete()`
masks the prompt again if the PII detector still finds something (COMPLIANCE P1).

Owner: Member 1 · Contract: config/models.yaml
"""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

from chaukas.core import m2_shim
from chaukas.db import ROOT
from chaukas.llm import replay

load_dotenv(ROOT / ".env")


class LLMUnavailable(Exception):
    """No provider could answer (no keys, network down, replay miss). Agents use their fallbacks."""


class LLMResult(BaseModel):
    text: str
    model: str
    source: str  # live | replay
    tokens_in: int = 0
    tokens_out: int = 0
    cost_inr: float = 0.0
    latency_ms: int = 0


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))


def _client(provider: dict):
    from openai import OpenAI  # imported lazily so tests without network never need it

    key = os.environ.get(provider["api_key_env"], "").strip()
    if not key:
        return None
    headers = {}
    if provider.get("extra_headers_key"):
        headers[provider["extra_headers_key"]] = key
    return OpenAI(base_url=provider["base_url"], api_key=key, default_headers=headers,
                  timeout=config()["call"]["timeout_s"], max_retries=0)


def _cost(provider: dict, tin: int, tout: int) -> float:
    return round(tin / 1000 * provider["cost_inr_per_1k_in"] + tout / 1000 * provider["cost_inr_per_1k_out"], 4)


def complete(agent: str, prompt: str, replay_key: str | None = None) -> LLMResult:
    """Call the routed model. Raises LLMUnavailable if nothing can answer."""
    cfg = config()
    rmode = replay.mode()

    if rmode == "replay":
        text = replay.lookup(agent, replay_key)
        if text is None:
            raise LLMUnavailable(f"replay miss for {agent}")
        return LLMResult(text=text, model="replay", source="replay")

    if m2_shim.detect(prompt):  # defence in depth: nothing raw may reach any model
        prompt = m2_shim.mask_text(prompt)

    last_err: Exception | None = None
    for name in cfg["route"]:
        provider = cfg["providers"][name]
        client = _client(provider)
        if client is None:
            last_err = LLMUnavailable(f"no API key for {name}")
            continue
        for _ in range(1 + cfg["call"]["retries_per_provider"]):
            t0 = time.perf_counter()
            try:
                resp = client.chat.completions.create(
                    model=provider["model"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=cfg["call"]["temperature"],
                    max_tokens=cfg["call"]["max_tokens"],
                )
                text = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                tin = getattr(usage, "prompt_tokens", 0) or 0
                tout = getattr(usage, "completion_tokens", 0) or 0
                if rmode == "record":
                    replay.record(agent, replay_key, text)
                return LLMResult(
                    text=text, model=provider["model"], source="live", tokens_in=tin, tokens_out=tout,
                    cost_inr=_cost(provider, tin, tout), latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            except Exception as exc:  # network, auth, rate limit ... try again / next provider
                last_err = exc

    # every provider failed -> recording safety net
    text = replay.lookup(agent, replay_key)
    if text is not None:
        return LLMResult(text=text, model="replay", source="replay")
    raise LLMUnavailable(str(last_err) if last_err else "no provider configured")


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM reply (handles <think>, code fences, chatter)."""
    text = _THINK.sub("", text)
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in LLM output")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in LLM output")
