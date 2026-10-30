"""Merchant-facing routes: GET /api/merchants, POST /api/sessions,
POST /api/sessions/{id}/messages, POST /api/sessions/{id}/confirm, GET /api/sessions/{id},
POST /api/sessions/{id}/voice (P1).

Thin router: no business logic (that lives in core/orchestrator.py).
Owner: Member 1 · Contract: CONTRACTS C5
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chaukas import db
from chaukas.core import m2_shim, orchestrator
from chaukas.core.models import TurnResponse
from chaukas.gateway import session as gw

router = APIRouter(prefix="/api")


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


class CreateSession(BaseModel):
    merchant_id: str
    channel: Literal["chat", "voice", "agent_desk"] = "chat"
    mode: Literal["autonomous", "copilot"] = "autonomous"


class SendMessage(BaseModel):
    text: str
    lang: str | None = None  # accepted for UI/voice; the intent agent detects language itself


class ConfirmBody(BaseModel):
    pending_audit_id: int | None = None
    approve: bool
    kind: Literal["consent", "step_up"] | None = None
    otp: str | None = None
    actor: Literal["merchant", "human"] = "merchant"
    actor_id: str | None = None


def _scenarios() -> dict[str, str]:
    try:
        data = json.loads((db.ROOT / "data" / "merchant_fixtures.json").read_text(encoding="utf-8"))
        return {m["merchant_id"]: m.get("scenario", "") for m in data["merchants"]}
    except Exception:
        return {}


@router.get("/merchants")
def list_merchants() -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT merchant_id, name, preferred_lang FROM merchants ORDER BY merchant_id").fetchall()
    finally:
        conn.close()
    scenarios = _scenarios()
    return [{"merchant_id": r["merchant_id"], "name_masked": m2_shim.mask(r["name"], "name"),
             "scenario": scenarios.get(r["merchant_id"], ""), "preferred_lang": r["preferred_lang"]}
            for r in rows]


@router.post("/sessions")
def create_session(body: CreateSession) -> dict:
    try:
        out = gw.create_session(body.merchant_id, body.channel, body.mode)
    except gw.MerchantNotFound:
        raise api_error(404, "MERCHANT_NOT_FOUND", f"unknown merchant {body.merchant_id}")
    return {"session_id": out["session_id"], "disclosure": out["disclosure"]}


@router.post("/sessions/{session_id}/messages", response_model=TurnResponse)
def post_message(session_id: str, body: SendMessage) -> TurnResponse:
    if not body.text.strip():
        raise api_error(422, "EMPTY_MESSAGE", "message text is empty")
    try:
        return orchestrator.handle_message(session_id, body.text)
    except gw.SessionNotFound:
        raise api_error(404, "SESSION_NOT_FOUND", f"unknown session {session_id}")


@router.post("/sessions/{session_id}/confirm", response_model=TurnResponse)
def confirm(session_id: str, body: ConfirmBody) -> TurnResponse:
    try:
        return orchestrator.handle_confirm(session_id, body.pending_audit_id, body.approve, body.kind,
                                           body.otp, body.actor, body.actor_id)
    except gw.SessionNotFound:
        raise api_error(404, "SESSION_NOT_FOUND", f"unknown session {session_id}")
    except orchestrator.PendingMismatch as exc:
        raise api_error(409, "NO_MATCHING_PENDING_STEP", str(exc))


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    try:
        session = gw.load_session(session_id)
    except gw.SessionNotFound:
        raise api_error(404, "SESSION_NOT_FOUND", f"unknown session {session_id}")
    conn = db.connect()
    try:
        turns = [dict(r) for r in conn.execute(
            "SELECT turn_no, trace_id, role, text_masked, lang, intent, created_at FROM turns "
            "WHERE session_id=? ORDER BY turn_no", (session_id,))]
    finally:
        conn.close()
    session.pop("pending_step_json", None)  # internal
    return {"session": session, "turns": turns}
