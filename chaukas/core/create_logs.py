"""Per-session agent logs: one folder per session, written automatically by the pipeline.

    logs/session_<session_id>/agent.log     human-readable, one block per event
    logs/session_<session_id>/agent.jsonl   same events, one JSON object per line (for scripts / eval)
    logs/session_<session_id>/llm_calls.log / .jsonl   every LLM call: full prompt + raw output

Events: `session_started` (gateway), `turn` (orchestrator, every merchant message / confirm button),
`human_resolve` (agent-desk approve), `llm_call` (llm/prompt.py). Everything goes through scrub() first:
no raw PII in logs (CLAUDE.md rule 5). The LLM's `thought_process` IS logged (its own THOUGHT section),
for debugging only: it is never shown to the merchant and never written to the DB. Logging must never
break a turn.

llm/prompt.py does not know the session, so every orchestrator entry point runs its turn inside
`with turn_scope(...)` (a contextvar: concurrent requests do not mix, and the binding ends with the turn).

Directory: env CHAUKAS_AGENT_LOG_DIR, default <repo>/logs (gitignored, like traces/).

Owner: Member 1
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator

from chaukas import db
from chaukas.core import m2_shim

log = logging.getLogger("chaukas.agent_logs")

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # session_id becomes a folder name: no '/' or '..'
_lock = threading.Lock()
_current: ContextVar[dict | None] = ContextVar("chaukas_log_turn", default=None)


def _never_raises(fn: Callable[..., None]) -> Callable[..., None]:
    """Every public log function is wrapped: logging can never fail a turn or change its response."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("agent log failed in %s", fn.__name__)
    return wrapper


def log_dir() -> Path:
    return Path(os.environ.get("CHAUKAS_AGENT_LOG_DIR") or db.ROOT / "logs")


def session_dir(session_id: str) -> Path:
    if not _SAFE_ID.match(session_id):
        raise ValueError("invalid session_id")
    return log_dir() / f"session_{session_id}"


def _write(session_id: str, event: dict[str, Any], text: str, stem: str = "agent") -> None:
    """Append one event to <stem>.jsonl and <stem>.log. Swallows every error: a log line is never worth
    a failed turn."""
    try:
        event = m2_shim.scrub({"ts": db.now_iso(), "session_id": session_id, **event})
        text = m2_shim.scrub(text)
        folder = session_dir(session_id)
        with _lock:
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / f"{stem}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            with open(folder / f"{stem}.log", "a", encoding="utf-8") as fh:
                fh.write(f"[{event['ts']}] {text.rstrip()}\n\n")
    except Exception:
        log.exception("agent log write failed (session %s)", session_id)


@contextmanager
def turn_scope(session_id: str, turn_no: int, trace_id: str) -> Iterator[None]:
    """LLM calls made inside this block are logged under this session/turn. The binding is undone on exit
    (also on an exception), so a call outside any turn is never logged under a previous session."""
    token = _current.set({"session_id": session_id, "turn_no": turn_no, "trace_id": trace_id})
    try:
        yield
    finally:
        _current.reset(token)


def _split_output(raw: str) -> tuple[str | None, str]:
    """(thought_process, pretty-printed output). Raw text is kept as is when it is not JSON."""
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except ValueError:
        return None, raw
    if not isinstance(data, dict):
        return None, raw
    thought = data.get("thought_process")
    return (str(thought) if thought is not None else None), json.dumps(data, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------
@_never_raises
def log_session_started(session_id: str, merchant_id: str, channel: str, mode: str, lang: str | None,
                        notice_version: str | None) -> None:
    event = {"event": "session_started", "merchant_id": merchant_id, "channel": channel, "mode": mode,
             "lang": lang, "notice_version": notice_version}
    text = (f"SESSION STARTED  merchant={merchant_id} channel={channel} mode={mode} lang={lang}\n"
            f"  disclosure sent (notice {notice_version})")
    _write(session_id, event, text)


@_never_raises
def log_turn(response: Any, message_masked: str, intent_confidence: float | None = None) -> None:
    """Called by the orchestrator with the finished TurnResponse of one turn."""
    r = response.model_copy(deep=True)  # the API response itself is never touched
    plan = [{"step_no": p.step_no, "action_type": p.action_type, "amount": p.amount} for p in r.plan]
    actions = [{"step_no": a.step_no, "action_type": a.action_type, "status": a.status, "ref_id": a.ref_id,
                "replayed": a.replayed} for a in r.actions]
    handoff = None
    if r.handoff is not None:
        handoff = {"reason_code": r.handoff.reason_code, "decision_needed": r.handoff.decision_needed}
    pending = None
    if r.pending_confirmation:
        pending = {k: r.pending_confirmation.get(k) for k in ("pending_audit_id", "kind", "reason_code")}
    spans = [{k: sp.get(k) for k in ("seq", "agent", "step_no", "input_summary", "output_summary", "status",
                                     "latency_ms", "model", "cost_inr")} for sp in (r.spans or [])]
    event = {
        "event": "turn", "turn_no": r.turn_no, "trace_id": r.trace_id, "status": r.status.value,
        "message_masked": message_masked, "intent": r.intent.value if r.intent else None,
        "intent_confidence": intent_confidence, "lang": r.lang, "plan": plan, "decisions": r.decisions,
        "actions": actions, "pending_confirmation": pending, "handoff": handoff, "reply": r.reply,
        "latency_ms": r.latency_ms, "cost_inr": r.cost_inr, "spans": spans,
    }

    lines = [f"TURN {r.turn_no}  trace={r.trace_id}  status={r.status.value}  "
             f"{r.latency_ms} ms  ₹{r.cost_inr}",
             f"  merchant : {message_masked}",
             f"  intent   : {event['intent']} ({r.lang}"
             + (f", conf {intent_confidence:.2f}" if intent_confidence is not None else "") + ")"]
    if plan:
        lines.append("  plan     : " + " → ".join(
            p["action_type"] + (f"(₹{p['amount']:,})" if p["amount"] else "") for p in plan))
    for d in r.decisions:
        lines.append(f"  guardrail: step {d['step_no']} {d['action_type']} → {d['verdict']} "
                     f"{d['reason_code']} ({d['reason']})")
    for a in actions:
        lines.append(f"  action   : step {a['step_no']} {a['action_type']} → {a['status']} {a['ref_id'] or ''}"
                     + (" (replayed)" if a["replayed"] else ""))
    if pending:
        lines.append(f"  pending  : {pending['kind']} ({pending['reason_code']}), audit #{pending['pending_audit_id']}")
    if handoff:
        lines.append(f"  handoff  : {handoff['reason_code']} — {handoff['decision_needed']}")
    lines.append(f"  reply    : {r.reply}")
    if spans:
        lines.append("  spans    :")
        for sp in spans:
            model = f" [{sp['model']} ₹{sp['cost_inr']}]" if sp["model"] else ""
            lines.append(f"    {sp['seq']:>2}. {sp['agent']:<9} {sp['latency_ms']:>5} ms  "
                         f"{sp['output_summary']}{model}")
    _write(r.session_id, event, "\n".join(lines))


@_never_raises
def log_human_resolve(session_id: str, staff_id: str, action_type: str, amount: int | None,
                      decision: Any | None, result: Any | None, error: str | None = None) -> None:
    """Agent-desk 'Approve & execute': who approved, what the guardrail said, what ran.
    Also called when the approve crashed (decision/result may be None, `error` set)."""
    event = {"event": "human_resolve", "staff_id": staff_id, "action_type": action_type, "amount": amount,
             "verdict": decision.verdict.value if decision else None,
             "reason_code": decision.reason_code.value if decision else None,
             "reason": decision.reason if decision else None, "audit_id": decision.audit_id if decision else None,
             "result": result.model_dump(mode="json") if result is not None else None, "error": error}
    text = (f"HUMAN RESOLVE  staff={staff_id}  {action_type}"
            + (f" ₹{amount:,}" if amount else "")
            + (f"\n  guardrail: {event['verdict']} {event['reason_code']} ({decision.reason})" if decision else
               "\n  guardrail: no decision")
            + (f"\n  action   : {result.status} {result.ref_id or ''}" if result is not None else
               "\n  action   : not executed")
            + (f"\n  ERROR    : {error}" if error else ""))
    _write(session_id, event, text)


@_never_raises
def log_llm_call(agent: str, template_file: str, attempt: int, prompt: str, *, output: str | None = None,
                 model: str | None = None, source: str | None = None, latency_ms: int = 0, tokens_in: int = 0,
                 tokens_out: int = 0, cost_inr: float = 0.0, error: str | None = None) -> None:
    """One LLM request: the full rendered prompt and the raw output (or the error). No-op outside a turn."""
    cur = _current.get()
    if cur is None:
        return
    thought, output = _split_output(output) if output is not None else (None, None)
    event = {"event": "llm_call", "turn_no": cur["turn_no"], "trace_id": cur["trace_id"], "agent": agent,
             "prompt_file": template_file, "attempt": attempt, "model": model, "source": source,
             "latency_ms": latency_ms, "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_inr": cost_inr,
             "thought_process": thought, "prompt": prompt, "output": output, "error": error}
    head = (f"LLM CALL  turn {cur['turn_no']}  agent={agent}  prompt={template_file}  attempt={attempt}  "
            + (f"model={model} ({source})  {latency_ms} ms  in={tokens_in} out={tokens_out} tok  ₹{cost_inr}"
               if error is None else f"ERROR: {error}"))
    bar = "-" * 30
    text = f"{head}\n{bar} PROMPT {bar}\n{prompt.rstrip()}\n"
    if thought is not None:
        text += f"{bar} THOUGHT {bar}\n{thought.strip()}\n"
    if output is not None:
        text += f"{bar} OUTPUT {bar}\n{output.rstrip()}\n"
    text += "=" * 80
    _write(cur["session_id"], event, text, stem="llm_calls")
