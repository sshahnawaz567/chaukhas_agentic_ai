"""Agent-desk (Mode 2) routes: GET /api/handoffs, GET /api/handoffs/{id},
POST /api/handoffs/{id}/resolve (human approve -> guardrail -> execute).

A human approval is NOT a bypass: the step goes through guardrail.check() with actor=human, and a BLOCK
stays a BLOCK (the handoff then stays open).

Owner: Member 1 · Contract: CONTRACTS C5
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from chaukas import db
from chaukas.api.chat import api_error
from chaukas.core import m2_shim, orchestrator
from chaukas.core.models import HandoffBrief, HandoffReason

router = APIRouter(prefix="/api")


class ResolveBody(BaseModel):
    staff_id: str
    decision: str = ""
    execute_suggested: bool = False


def _row(handoff_id: str):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise api_error(404, "HANDOFF_NOT_FOUND", f"unknown handoff {handoff_id}")
    return row


@router.get("/handoffs")
def list_handoffs(status: str = "open") -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT id, merchant_id, reason_code, decision_needed, created_at FROM handoffs "
            "WHERE status=? ORDER BY created_at, id", (status,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.get("/handoffs/{handoff_id}")
def get_handoff(handoff_id: str) -> dict:
    row = _row(handoff_id)
    brief = HandoffBrief.model_validate_json(row["brief_json"])
    timeline: list[dict] = []
    if row["ticket_id"]:
        conn = db.connect()
        try:
            timeline = [dict(r) for r in conn.execute(
                "SELECT created_at, actor, actor_id, event_type, detail FROM ticket_events "
                "WHERE ticket_id=? ORDER BY created_at, id", (row["ticket_id"],))]
        finally:
            conn.close()
    return {
        "id": row["id"], "session_id": row["session_id"], "merchant_id": row["merchant_id"],
        "ticket_id": row["ticket_id"], "trace_id": row["trace_id"], "status": row["status"],
        "assigned_to": row["assigned_to"], "human_decision": row["human_decision"],
        "created_at": row["created_at"], "resolved_at": row["resolved_at"],
        "brief": brief.model_dump(mode="json"), "ticket_events": timeline,
    }


@router.post("/handoffs/{handoff_id}/resolve")
def resolve(handoff_id: str, body: ResolveBody) -> dict:
    row = _row(handoff_id)
    if row["status"] == "resolved":
        raise api_error(409, "HANDOFF_ALREADY_RESOLVED", f"{handoff_id} is already resolved")
    brief = HandoffBrief.model_validate_json(row["brief_json"])
    decision_out = None
    result = None
    executed_ok = False

    if body.execute_suggested:
        if brief.suggested_step is None or brief.pending_audit_id is None:
            raise api_error(400, "NOTHING_TO_EXECUTE", "this brief has no suggested step to execute")
        decision, result, _state = orchestrator.resolve_by_human(
            row["session_id"], row["merchant_id"], brief.suggested_step, brief.pending_audit_id,
            brief.confirmation_kind or "step_up", body.staff_id)
        decision_out = decision.model_dump(mode="json")
        executed_ok = result is not None and result.status == "success"
        if not executed_ok:  # BLOCK is final / tool failed: the handoff stays open for a human to rethink
            return {"handoff": get_handoff(handoff_id), "decision": decision_out,
                    "action_result": result.model_dump(mode="json") if result else None}

    now = db.now_iso()
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE handoffs SET status='resolved', assigned_to=?, human_decision=?, resolved_at=? WHERE id=?",
            (body.staff_id, m2_shim.scrub(body.decision or ("approved: executed suggested step" if executed_ok else "resolved")),
             now, handoff_id))
        if brief.reason_code != HandoffReason.LOAN_ACCEPTED.value:
            # a loan follow-up is back-office work on a request Chaukas already resolved: closing it must not
            # turn an autonomous resolution into 'resolved_by_human' (eval: autonomous resolution metric)
            conn.execute("UPDATE sessions SET outcome='resolved_by_human', ended_at=? WHERE session_id=?",
                         (now, row["session_id"]))
        if row["ticket_id"]:
            what = (f"approved and executed {brief.suggested_step.action_type}"
                    f"{' of ₹' + format(brief.suggested_step.amount, ',') if brief.suggested_step.amount else ''}"
                    if executed_ok and brief.suggested_step else (body.decision or "resolved without execution"))
            conn.execute(
                "INSERT INTO ticket_events (ticket_id, session_id, actor, actor_id, event_type, detail) VALUES (?,?,?,?,?,?)",
                (row["ticket_id"], row["session_id"], "human", body.staff_id, "action_taken", m2_shim.scrub(what)))
            conn.execute(
                "UPDATE tickets SET status='resolved', resolved_by='human', resolution=?, resolved_at=? WHERE id=?",
                (m2_shim.scrub(what), now, row["ticket_id"]))
            conn.execute(
                "INSERT INTO ticket_events (ticket_id, session_id, actor, actor_id, event_type, detail) VALUES (?,?,?,?,?,?)",
                (row["ticket_id"], row["session_id"], "human", body.staff_id, "resolved", "handoff resolved by human"))
        conn.commit()
    finally:
        conn.close()
    return {"handoff": get_handoff(handoff_id), "decision": decision_out,
            "action_result": result.model_dump(mode="json") if result else None}
