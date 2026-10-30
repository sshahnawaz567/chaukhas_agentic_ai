"""Trace emitter + ops API (audit, red-team check, eval scorecard).

Owner: Member 2 · Contract: CONTRACTS C3 (Span), C5
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chaukas.api import ops
from chaukas.observability import trace
from data.seed import seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "ops.db"
    seed(db_path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(db_path))
    monkeypatch.setenv("CHAUKAS_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("CHAUKAS_EVAL_PATH", str(tmp_path / "latest.json"))
    app = FastAPI()
    app.include_router(ops.router)
    return TestClient(app)


def step(action, params, amount=None, step_no=1):
    return {"step_no": step_no, "action_type": action, "params": params, "amount": amount, "rationale": "redteam"}


def check(client, merchant, action, params, amount=None, **extra):
    r = client.post("/api/redteam/check", json={"merchant_id": merchant, "step": step(action, params, amount), **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ trace.py

def test_emit_writes_scrubbed_jsonl_with_increasing_seq(client):
    s1 = trace.emit("T1", "S1", 1, "gateway", "mera phone +919800000001 hai", "ok")
    s2 = trace.emit("T1", "S1", 1, "guardrail", "retrigger_payout 18400", "ALLOW", step_no=1, latency_ms=3, cost_inr=0.0)
    assert (s1.seq, s2.seq) == (1, 2)
    raw = (trace.trace_dir() / "T1.jsonl").read_text(encoding="utf-8")
    assert "9800000001" not in raw and "XXXXXX0001" in raw
    assert [s.agent for s in trace.read_trace("T1")] == ["gateway", "guardrail"]
    assert len(raw.strip().splitlines()) == 2 and all(json.loads(line) for line in raw.splitlines())


@pytest.mark.parametrize("bad", ["../secret", "a/b", "..", "a b", "x" * 65, ""])
def test_trace_id_cannot_escape_the_traces_folder(client, bad):
    with pytest.raises(ValueError):
        trace.emit(bad, "S1", 1, "gateway", "x", "y")
    assert trace.read_trace(bad) == []


def test_long_summary_is_clipped(client):
    span = trace.emit("T2", "S1", 1, "reply", "x" * 5000, "y")
    assert len(span.input_summary) < 1100


# ------------------------------------------------------------------ GET /api/traces

def test_get_trace_returns_spans_or_404(client):
    trace.emit("T3", "S1", 1, "intent", "in", "out")
    r = client.get("/api/traces/T3")
    assert r.status_code == 200 and r.json()[0]["agent"] == "intent"
    miss = client.get("/api/traces/NOPE")
    assert miss.status_code == 404 and miss.json()["error"]["code"] == "TRACE_NOT_FOUND"
    assert client.get("/api/traces/..%2Fetc").status_code in (404, 400)


# ------------------------------------------------------------------ POST /api/redteam/check (demo scene 4)

def test_redteam_injection_amount_is_blocked_by_ledger(client):
    d = check(client, "M005", "retrigger_payout", {"settlement_id": "SET-71209", "amount": 100000}, 100000)
    assert (d["verdict"], d["reason_code"]) == ("BLOCK", "LEDGER_MISMATCH")


def test_redteam_debit_is_never_allowed(client):
    d = check(client, "M020", "debit_merchant_account", {"merchant_id": "M020", "amount": 5000}, 5000)
    assert (d["verdict"], d["reason_code"]) == ("BLOCK", "NEVER_ALLOWED")


@pytest.mark.parametrize("merchant,settlement,amount,verdict", [
    ("M019", "SET-10488", 24999, "ALLOW"),
    ("M012", "SET-96101", 25000, "ALLOW"),
    ("M007", "SET-82150", 25001, "NEEDS_CONFIRMATION"),
])
def test_redteam_boundary_trio(client, merchant, settlement, amount, verdict):
    d = check(client, merchant, "retrigger_payout", {"settlement_id": settlement, "amount": amount}, amount)
    assert d["verdict"] == verdict


def test_redteam_never_executes_and_is_audited_as_system(client):
    check(client, "M012", "retrigger_payout", {"settlement_id": "SET-96101", "amount": 25000}, 25000)
    from chaukas.db import connect
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 0
    assert conn.execute("SELECT actor FROM audit_log").fetchone()[0] == "system"
    conn.close()
    # repeating it is not a DUPLICATE_ACTION: every call is a fresh redteam session
    assert check(client, "M012", "retrigger_payout", {"settlement_id": "SET-96101", "amount": 25000}, 25000)["verdict"] == "ALLOW"


def test_redteam_offer_uses_supplied_eligibility_or_fails_closed(client):
    offer = {"merchant_id": "M003", "amount": 20000}
    assert check(client, "M003", "create_offer", offer, 20000)["reason_code"] == "OFFER_NOT_ELIGIBLE"
    ineligible = {"eligible": False, "max_amount": 0, "reason_codes": ["AVG_BALANCE_LOW"]}
    assert check(client, "M003", "create_offer", offer, 20000, eligibility=ineligible)["reason_code"] == "OFFER_NOT_ELIGIBLE"
    cooling = {"eligible": True, "max_amount": 55000, "reason_codes": []}
    d = check(client, "M018", "create_offer", {"merchant_id": "M018", "amount": 55000}, 55000, eligibility=cooling)
    assert d["reason_code"] == "OFFER_COOLING_OFF"


def test_redteam_unknown_merchant_is_404(client):
    r = client.post("/api/redteam/check", json={"merchant_id": "M999", "step": step("verify_ledger", {"settlement_id": "x"})})
    assert r.status_code == 404 and r.json()["error"]["code"] == "MERCHANT_NOT_FOUND"


# ------------------------------------------------------------------ GET /api/audit (demo scene 5)

def test_audit_lists_decisions_with_execution_status(client):
    check(client, "M012", "retrigger_payout", {"settlement_id": "SET-96101", "amount": 25000}, 25000)
    check(client, "M005", "retrigger_payout", {"settlement_id": "SET-71209", "amount": 100000}, 100000)
    rows = client.get("/api/audit").json()
    assert [r["guardrail_decision"] for r in rows] == ["ALLOW", "BLOCK"]            # oldest first
    assert rows[1]["reason_code"] == "LEDGER_MISMATCH" and rows[0]["execution_status"] is None
    assert all("rollback_token" not in r for r in rows)
    assert [r["merchant_id"] for r in client.get("/api/audit?merchant_id=M005").json()] == ["M005"]
    assert client.get("/api/audit?merchant_id=M001").json() == []
    assert client.get("/api/audit?limit=1").json()[0]["merchant_id"] == "M005"       # the latest one


def test_audit_shows_execution_status_after_the_action_agent_ran(client):
    from chaukas.db import connect
    from chaukas.observability import audit
    d = check(client, "M012", "retrigger_payout", {"settlement_id": "SET-96101", "amount": 25000}, 25000)
    conn = connect()
    audit.start_execution(conn, idempotency_key="k1", audit_id=d["audit_id"], trace_id="t", session_id="s",
                          merchant_id="M012", action_type="retrigger_payout", amount=25000)
    audit.finish_execution(conn, "k1", "success", result_ref="PAY-1")
    conn.close()
    row = client.get("/api/audit?merchant_id=M012").json()[0]
    assert (row["execution_status"], row["result_ref"]) == ("success", "PAY-1")


# ------------------------------------------------------------------ GET /api/eval/latest

def test_eval_latest_404_until_the_eval_has_run(client, tmp_path):
    assert client.get("/api/eval/latest").json()["error"]["code"] == "EVAL_NOT_RUN"
    score = {"unsafe_actions": {"value": 0, "target": 0, "pass": True}}
    (tmp_path / "latest.json").write_text(json.dumps(score), encoding="utf-8")
    assert client.get("/api/eval/latest").json() == score
