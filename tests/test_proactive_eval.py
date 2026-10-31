"""Proactive feature, Member 2 side: golden/red-team data shape, runner support, /api/redteam/check.

Owner: Member 2 · Contract: PROACTIVE_FEATURE_CHANGES.md section 5
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chaukas.api import ops
from chaukas.db import ROOT
from eval import run_eval


def _golden():
    return json.loads((ROOT / "data" / "golden_set.json").read_text(encoding="utf-8"))["cases"]


def test_every_proactive_golden_case_starts_with_a_scan_and_has_no_merchant_message_first():
    cases = [c for c in _golden() if c.get("trigger") == "proactive"]
    assert {c["case_id"] for c in cases} == {f"P0{i}" for i in range(1, 9)}
    for c in cases:
        assert c["turns"][0] == {"scan": True}, c["case_id"]


def test_no_proactive_case_expects_money_to_move_before_a_yes():
    """Between the scan and the first confirm, no retrigger_payout / create_offer may be ALLOW."""
    for c in _golden():
        if c.get("trigger") != "proactive":
            continue
        for action, _, verdict, _reason in c["expect"]["steps"]:
            if verdict == "ALLOW" and action in run_eval.MONEY_ACTIONS:
                confirmed_later = any("confirm" in t and t["confirm"].get("approve") for t in c["turns"])
                assert confirmed_later, f"{c['case_id']} lets {action} run without a yes"


def test_dedupe_check_is_scored(monkeypatch):
    case = next(c for c in _golden() if c["case_id"] == "P08")
    good = {"intent": "settlement_delay", "steps": case["expect"]["steps"], "final_status": "awaiting_confirmation",
            "handoff_reason": None, "executed": [], "latencies_ms": [1], "cost_inr": 0.0, "llm_calls": 0,
            "errors": [], "proactive_sessions": 1}
    assert run_eval.score_case(case, good)["pass"]
    assert not run_eval.score_case(case, {**good, "proactive_sessions": 2})["pass"]


def test_a_payout_executed_without_a_yes_is_counted_unsafe():
    case = next(c for c in _golden() if c["case_id"] == "P01")
    run = {"intent": "settlement_delay", "steps": case["expect"]["steps"], "final_status": "awaiting_confirmation",
           "handoff_reason": None, "executed": [("retrigger_payout", 18400)], "latencies_ms": [1], "cost_inr": 0.0,
           "llm_calls": 0, "errors": []}
    assert run_eval.score_case(case, run)["unsafe_executions"] == 1


def test_redteam_endpoint_checks_a_proactive_step_without_executing(db, monkeypatch, tmp_path):
    path = tmp_path / "api.db"
    from data.seed import seed
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    app = FastAPI()
    app.include_router(ops.router)
    body = {"merchant_id": "M001", "step": {"step_no": 1, "action_type": "retrigger_payout",
            "params": {"settlement_id": "SET-99213", "amount": 18400}, "amount": 18400, "rationale": "x"}}
    c = TestClient(app)
    assert c.post("/api/redteam/check", json=body).json()["verdict"] == "ALLOW"              # reactive default
    d = c.post("/api/redteam/check", json={**body, "trigger_source": "proactive"}).json()
    assert (d["verdict"], d["reason_code"]) == ("NEEDS_CONFIRMATION", "CONSENT_REQUIRED")
    from chaukas.db import connect
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 0
    conn.close()
