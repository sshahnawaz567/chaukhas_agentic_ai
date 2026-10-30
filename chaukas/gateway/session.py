"""Session create/load, turn numbering, AI disclosure message,
PII masking of the incoming message at ingestion (privacy.mask_text).

Owner: Member 1 · Contract: CONTRACTS C1
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from chaukas import db
from chaukas.core import m2_shim
from chaukas.core.models import PlannedStep, TurnRecord
from chaukas.integrations._common import load_config


class SessionNotFound(LookupError):
    pass


class MerchantNotFound(LookupError):
    pass


# step_no is MONOTONIC PER SESSION. Seeded from the audit log so a restart cannot reuse a number that
# already produced an idempotency key; read-only steps never hit the log, so reuse there is harmless.
_STEP_COUNTERS: dict[str, int] = {}


def next_step_no(session_id: str) -> int:
    """Next unused step number for this session (does not consume it)."""
    if session_id not in _STEP_COUNTERS:
        conn = db.connect()
        try:
            row = conn.execute("SELECT MAX(step_no) AS m FROM audit_log WHERE session_id=?",
                               (session_id,)).fetchone()
            ex = conn.execute("SELECT idempotency_key FROM executions WHERE session_id=?",
                              (session_id,)).fetchall()
        finally:
            conn.close()
        used = [row["m"]] if row and row["m"] is not None else []
        used += [int(r["idempotency_key"].rsplit(":", 1)[1]) for r in ex]
        _STEP_COUNTERS[session_id] = (max(used) + 1) if used else 1
    return _STEP_COUNTERS[session_id]


def advance_step_no(session_id: str, used_up_to: int) -> None:
    _STEP_COUNTERS[session_id] = max(next_step_no(session_id), used_up_to + 1)


def create_session(merchant_id: str, channel: str, mode: str) -> dict[str, Any]:
    """Insert a session and return {session_id, disclosure, lang}. The disclosure is stored as turn 1."""
    conn = db.connect()
    try:
        m = conn.execute("SELECT preferred_lang FROM merchants WHERE merchant_id=?", (merchant_id,)).fetchone()
        if not m:
            raise MerchantNotFound(merchant_id)
        session_id = "S-" + uuid.uuid4().hex[:10]
        lang = m["preferred_lang"]
        conn.execute("INSERT INTO sessions (session_id, merchant_id, channel, mode, lang) VALUES (?,?,?,?,?)",
                     (session_id, merchant_id, channel, mode, lang))
        text, _notice_version = m2_shim.get_disclosure(lang)
        conn.execute("INSERT INTO turns (session_id, turn_no, trace_id, role, text_masked, lang) VALUES (?,?,?,?,?,?)",
                     (session_id, 1, "gateway-" + session_id, "agent", text, lang))
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id, "disclosure": text, "lang": lang}


def load_session(session_id: str) -> dict[str, Any]:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise SessionNotFound(session_id)
    return dict(row)


def mask_incoming(text: str) -> str:
    """Raw merchant text never goes past this function: everything downstream sees the masked form."""
    return m2_shim.mask_text(text.strip())


def history(session_id: str, limit: int | None = None) -> list[TurnRecord]:
    limit = limit or int(load_config("mock").get("history_window", 6))
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT turn_no, role, text_masked, lang FROM turns WHERE session_id=? ORDER BY turn_no DESC LIMIT ?",
            (session_id, limit)).fetchall()
    finally:
        conn.close()
    return [TurnRecord(**dict(r)) for r in reversed(rows)]


def next_turn_no(session_id: str) -> int:
    conn = db.connect()
    try:
        row = conn.execute("SELECT MAX(turn_no) AS m FROM turns WHERE session_id=?", (session_id,)).fetchone()
    finally:
        conn.close()
    return (row["m"] or 0) + 1


def record_turn(session_id: str, turn_no: int, trace_id: str, role: str, text_masked: str,
                lang: str | None, intent: str | None = None) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO turns (session_id, turn_no, trace_id, role, text_masked, lang, intent) VALUES (?,?,?,?,?,?,?)",
            (session_id, turn_no, trace_id, role, m2_shim.scrub(text_masked), lang, intent))
        conn.commit()
    finally:
        conn.close()


def save_session_state(session_id: str, *, lang: str | None, intent: str | None, urgency: str | None,
                       track: str | None, pending: tuple[PlannedStep, dict, int | None] | None,
                       outcome: str | None) -> None:
    """Persist the latest understanding + the pending step (or clear it) + the outcome."""
    pending_json = None
    audit_id = None
    if pending is not None:
        step, meta, audit_id = pending
        pending_json = json.dumps({"step": step.model_dump(mode="json"), "meta": meta}, ensure_ascii=False)
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE sessions SET lang=COALESCE(?,lang), intent=COALESCE(?,intent), urgency=COALESCE(?,urgency),
                      track=COALESCE(?,track), pending_step_json=?, pending_audit_id=?, outcome=COALESCE(?,outcome)
               WHERE session_id=?""",
            (lang, intent, urgency, track, pending_json, audit_id, outcome, session_id))
        conn.commit()
    finally:
        conn.close()


def load_pending(session: dict[str, Any]) -> tuple[PlannedStep, dict, int | None] | None:
    if not session.get("pending_step_json"):
        return None
    blob = json.loads(session["pending_step_json"])
    return PlannedStep.model_validate(blob["step"]), blob.get("meta") or {}, session.get("pending_audit_id")
