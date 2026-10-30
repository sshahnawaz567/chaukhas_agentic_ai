"""Observability/eval routes: GET /api/traces/{trace_id}, GET /api/audit,
POST /api/redteam/check (guardrail only, never executes), GET /api/eval/latest.

Owner: Member 2 · Contract: CONTRACTS C5

Member 1 mounts it in chaukas/main.py:  app.include_router(ops.router)
"""
import json
import os
import uuid
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from chaukas.agents import guardrail
from chaukas.core.models import (
    Channel, ConversationState, LenderDecision, MerchantContext, Mode, PlannedStep,
)
from chaukas.db import ROOT, connect, query_all, query_one
from chaukas.observability import trace

router = APIRouter(prefix="/api")


def _error(status: int, code: str, message: str) -> JSONResponse:
    """The error shape every route uses (CONTRACTS C5)."""
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def eval_result_path() -> Path:
    """Where eval/run_eval.py writes the scorecard. CHAUKAS_EVAL_PATH overrides it (tests)."""
    return Path(os.environ.get("CHAUKAS_EVAL_PATH") or ROOT / "eval" / "latest.json")


# ------------------------------------------------------------------ traces

@router.get("/traces/{trace_id}")
def get_trace(trace_id: str):
    spans = trace.read_trace(trace_id)
    if not spans:
        return _error(404, "TRACE_NOT_FOUND", "no trace with that id")
    return [s.model_dump(mode="json") for s in spans]


# ------------------------------------------------------------------ audit

@router.get("/audit")
def get_audit(merchant_id: str | None = None, session_id: str | None = None,
              limit: int = Query(200, ge=1, le=1000)):
    """Guardrail decisions joined with execution status, oldest first (the latest `limit` rows).
    rollback_token is deliberately not returned."""
    where, params = [], []
    for column, value in (("a.merchant_id", merchant_id), ("a.session_id", session_id)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    sql = (
        "SELECT a.id, a.ts, a.actor, a.merchant_id, a.session_id, a.trace_id, a.step_no, a.action_type, "
        "a.amount, a.params_masked, a.guardrail_decision, a.reason_code, a.reason, a.ticket_id, "
        "a.confirms_audit_id, e.status AS execution_status, e.result_ref "
        "FROM audit_log a LEFT JOIN executions e ON e.audit_id = a.id "
        + ("WHERE " + " AND ".join(where) + " " if where else "")
        + "ORDER BY a.id DESC LIMIT ?"
    )
    with closing(connect()) as conn:
        rows = query_all(conn, sql, (*params, limit))
    return [dict(r) for r in reversed(rows)]


# ------------------------------------------------------------------ red-team: "assume the LLM is compromised"

class RedteamRequest(BaseModel):
    merchant_id: str
    step: PlannedStep
    # Optional lender answer, so offer attacks (ineligible / cooling-off) can be tried. If omitted the
    # guardrail sees no eligibility and fails closed for create_offer.
    eligibility: LenderDecision | None = None


@router.post("/redteam/check")
def redteam_check(req: RedteamRequest):
    """Run guardrail.check() on a hand-crafted step. NEVER executes anything: no executions row, no tool call.
    The decision is audited with actor='system'."""
    with closing(connect()) as conn:
        merchant = query_one(conn, "SELECT preferred_lang, kyc_status, device, gmv_30d, bank_details_updated_at "
                                   "FROM merchants WHERE merchant_id = ?", (req.merchant_id,))
        if merchant is None:
            return _error(404, "MERCHANT_NOT_FOUND", "no merchant with that id")

        context = None
        if req.eligibility is not None:
            context = MerchantContext(
                merchant_id=req.merchant_id, name_masked="****", account_ref="redteam",
                preferred_lang=merchant["preferred_lang"], kyc_status=merchant["kyc_status"],
                device=merchant["device"], gmv_30d=merchant["gmv_30d"],
                bank_details_updated_at=merchant["bank_details_updated_at"], settlements=[], open_tickets=[],
                has_open_handoff=False, declined_offer_recently=False, eligibility=req.eligibility)

        run_id = uuid.uuid4().hex[:8]
        state = ConversationState(
            session_id=f"redteam-{run_id}", turn_no=0, trace_id=f"redteam-{run_id}", merchant_id=req.merchant_id,
            channel=Channel.CHAT, mode=Mode.AUTONOMOUS, message_masked="red-team check", merchant=context)
        decision = guardrail.check(req.step, state, conn=conn, actor="system")
    return decision.model_dump(mode="json")


# ------------------------------------------------------------------ eval scorecard

@router.get("/eval/latest")
def get_eval_latest():
    path = eval_result_path()
    if not path.exists():
        return _error(404, "EVAL_NOT_RUN", "no eval result yet: run `python -m eval.run_eval`")
    return json.loads(path.read_text(encoding="utf-8"))
