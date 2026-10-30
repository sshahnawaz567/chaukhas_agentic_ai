"""Span emitter (scrubbed) -> traces/{trace_id}.jsonl. Latency, tokens, cost per step.

Owner: Member 2 · Contract: CONTRACTS C3 (Span)

One Span per agent step. Every span is written as one JSON line, and its summaries are scrubbed first,
so a trace file can be shown on screen (demo scene 5) without leaking PII.
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from chaukas.db import ROOT
from chaukas.privacy.scrub import scrub

# trace_id becomes a file name, so it must never contain a path separator or '..'
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_SUMMARY = 1000
_lock = threading.Lock()


class Span(BaseModel):
    trace_id: str
    session_id: str
    turn_no: int
    seq: int
    agent: Literal["gateway", "intent", "context", "planner", "guardrail", "action", "handoff", "reply"]
    step_no: int | None = None
    input_summary: str                       # masked
    output_summary: str                      # masked
    status: Literal["ok", "error"]
    latency_ms: int
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_inr: float = 0.0
    ts: str


def is_valid_trace_id(trace_id: str) -> bool:
    return bool(_SAFE_ID.match(trace_id))


def trace_dir() -> Path:
    """traces/ in the repo root, or CHAUKAS_TRACE_DIR (tests)."""
    return Path(os.environ.get("CHAUKAS_TRACE_DIR") or ROOT / "traces")


def _path(trace_id: str) -> Path:
    if not is_valid_trace_id(trace_id):
        raise ValueError("invalid trace_id")
    return trace_dir() / f"{trace_id}.jsonl"


def _clip(text: str) -> str:
    text = scrub(text)
    return text if len(text) <= _MAX_SUMMARY else text[:_MAX_SUMMARY] + "..."


def emit(
    trace_id: str, session_id: str, turn_no: int,
    agent: Literal["gateway", "intent", "context", "planner", "guardrail", "action", "handoff", "reply"],
    input_summary: str, output_summary: str, *, status: Literal["ok", "error"] = "ok",
    step_no: int | None = None, latency_ms: int = 0, model: str | None = None,
    tokens_in: int = 0, tokens_out: int = 0, cost_inr: float = 0.0,
) -> Span:
    """Append one scrubbed span to traces/{trace_id}.jsonl and return it. seq counts up per trace."""
    path = _path(trace_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        seq = sum(1 for _ in path.open(encoding="utf-8")) + 1 if path.exists() else 1
        span = Span(
            trace_id=trace_id, session_id=session_id, turn_no=turn_no, seq=seq, agent=agent, step_no=step_no,
            input_summary=_clip(input_summary), output_summary=_clip(output_summary), status=status,
            latency_ms=latency_ms, model=model, tokens_in=tokens_in, tokens_out=tokens_out, cost_inr=cost_inr,
            ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(span.model_dump_json() + "\n")
    return span


def read_trace(trace_id: str) -> list[Span]:
    """All spans of one trace in order. Unknown or invalid trace_id -> empty list."""
    if not is_valid_trace_id(trace_id):
        return []
    path = _path(trace_id)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [Span.model_validate_json(line) for line in f if line.strip()]
