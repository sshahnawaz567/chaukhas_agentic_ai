"""Money state is NEVER cached (CLAUDE.md rule 4): settlements, balances, eligibility, daily totals and guardrail
decisions are read fresh from the DB on every call.

Owner: Member 2 · CLAUDE.md rule 4

Each test changes the database BETWEEN two identical calls and shows the second answer changed. A cache would
return the first answer again. A static guard also fails if anyone adds a cached function that touches the DB.
"""
import ast
import json
from pathlib import Path

import pytest
import yaml

from chaukas.agents import context, guardrail
from chaukas.db import ROOT, connect
from chaukas.integrations import lending
from chaukas.observability import audit
from chaukas.policy import engine
from data.seed import seed


@pytest.fixture
def cdb(tmp_path, monkeypatch):
    path = tmp_path / "cache.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    conn = connect(path)
    yield conn
    conn.close()


def check(conn, make_state, make_step, merchant_id, settlement_id, amount, now=None):
    step = make_step("retrigger_payout", {"settlement_id": settlement_id, "amount": amount}, amount=amount)
    d = guardrail.check(step, make_state(merchant_id), None, conn=conn, policy=engine.load_policy(), now=now)
    return d.verdict.value, d.reason_code.value


# ------------------------------------------------------------------ reads are fresh

def test_the_merchant_context_follows_the_ledger_between_two_loads(cdb):
    before = next(s for s in context.load("M009").settlements if s.id == "SET-90123")
    assert (before.amount, before.status) == (26500, "failed")
    cdb.execute("UPDATE settlements SET amount = 31000, status = 'pending' WHERE id = 'SET-90123'")
    cdb.commit()
    after = next(s for s in context.load("M009").settlements if s.id == "SET-90123")
    assert (after.amount, after.status) == (31000, "pending")


def test_loan_eligibility_follows_the_cashflow_between_two_calls(cdb):
    assert lending.check_eligibility("M003").eligible is False
    cdb.execute("UPDATE cashflow_features SET avg_balance = 90000, inflow_30d = 200000 WHERE merchant_id = 'M003'")
    cdb.commit()
    now_eligible = lending.check_eligibility("M003")
    assert now_eligible.eligible is True and now_eligible.max_amount > 0
    cdb.execute("UPDATE cashflow_features SET avg_balance = 100 WHERE merchant_id = 'M003'")
    cdb.commit()
    assert lending.check_eligibility("M003").eligible is False


# ------------------------------------------------------------------ guardrail decisions are never reused

def test_the_same_step_gets_a_new_decision_when_the_ledger_changes(cdb, make_state, make_step):
    assert check(cdb, make_state, make_step, "M009", "SET-90123", 26500) == ("NEEDS_CONFIRMATION", "OVER_AUTO_LIMIT")
    cdb.execute("UPDATE settlements SET amount = 20000 WHERE id = 'SET-90123'")
    cdb.commit()
    assert check(cdb, make_state, make_step, "M009", "SET-90123", 20000) == ("ALLOW", "WITHIN_POLICY")
    # the old step (26500) no longer matches the ledger: it is a mismatch now, not the cached over-limit answer
    assert check(cdb, make_state, make_step, "M009", "SET-90123", 26500) == ("BLOCK", "LEDGER_MISMATCH")
    cdb.execute("UPDATE settlements SET status = 'success', cause = NULL WHERE id = 'SET-90123'")
    cdb.commit()
    assert check(cdb, make_state, make_step, "M009", "SET-90123", 20000)[0] == "BLOCK"


def test_the_daily_total_is_read_from_the_executions_table_on_every_check(cdb, make_state, make_step):
    assert check(cdb, make_state, make_step, "M014", "SET-98102", 14000) == ("ALLOW", "WITHIN_POLICY")
    # 15,000 goes out earlier today, in another conversation (what the Action agent records) ...
    audit_id = cdb.execute("INSERT INTO audit_log (trace_id, session_id, merchant_id, actor, step_no, action_type, amount, "
                           "params_masked, guardrail_decision, reason_code, reason, rollback_token) VALUES "
                           "('t','S0','M014','agent',1,'retrigger_payout',15000,'{}','ALLOW','WITHIN_POLICY','ok','rb1')").lastrowid
    audit.start_execution(cdb, idempotency_key="S0:1", audit_id=audit_id, trace_id="t", session_id="S0",
                          merchant_id="M014", action_type="retrigger_payout", amount=15000)
    audit.finish_execution(cdb, "S0:1", "success", result_ref="PAY-1")
    # ... so the SAME 14,000 step is now over the daily limit
    assert check(cdb, make_state, make_step, "M014", "SET-98102", 14000) == ("NEEDS_CONFIRMATION", "OVER_DAILY_LIMIT")
    # and tomorrow the window is clean again: the check is a fresh query for "today", not a remembered total
    tomorrow = engine.datetime.now(engine.timezone.utc) + engine.timedelta(days=1, hours=1)
    assert check(cdb, make_state, make_step, "M014", "SET-98102", 14000, now=tomorrow) == ("ALLOW", "WITHIN_POLICY")


def test_a_policy_edit_takes_effect_on_the_next_call(tmp_path):
    """The kill switch (disabled_actions) must work without a restart."""
    policy = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text(encoding="utf-8"))
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    assert engine.load_policy(path)["disabled_actions"] == []
    policy["disabled_actions"] = ["retrigger_payout"]
    policy["auto_limit_inr"] = 1000
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    fresh = engine.load_policy(path)
    assert fresh["disabled_actions"] == ["retrigger_payout"] and fresh["auto_limit_inr"] == 1000


def test_a_disabled_action_is_blocked_at_once(cdb, make_state, make_step):
    policy = engine.load_policy()
    policy["disabled_actions"] = ["retrigger_payout"]
    step = make_step("retrigger_payout", {"settlement_id": "SET-90123", "amount": 26500}, amount=26500)
    d = guardrail.check(step, make_state("M009"), None, conn=cdb, policy=policy)
    assert (d.verdict.value, d.reason_code.value) == ("BLOCK", "ACTION_DISABLED")


# ------------------------------------------------------------------ the whole loop, end to end

def test_the_orchestrator_plans_from_the_ledger_as_it_is_now(cdb, monkeypatch):
    """Same merchant, same words, the ledger changes between two sessions: the plan and the verdict change with it."""
    pytest.importorskip("chaukas.core.orchestrator")
    from chaukas.core import m2_shim, orchestrator
    from chaukas.gateway import session as gw
    from chaukas.llm import prompt as llm_prompt
    from chaukas.llm.client import LLMUnavailable

    def no_llm(*a, **kw):
        raise LLMUnavailable("offline")
    monkeypatch.setattr(llm_prompt, "complete", no_llm)
    monkeypatch.setattr(m2_shim, "emit_span", lambda span: None)

    def ask():
        sid = gw.create_session("M012", "chat", "autonomous")["session_id"]
        resp = orchestrator.handle_message(sid, "Mera settlement nahi aaya")
        return resp, [(d["action_type"], d["verdict"], d["reason_code"]) for d in resp.decisions if d["action_type"] == "retrigger_payout"]

    cdb.execute("UPDATE settlements SET amount = 26000 WHERE id = 'SET-96101'")
    cdb.commit()
    resp, retrigger = ask()
    assert retrigger == [("retrigger_payout", "NEEDS_CONFIRMATION", "OVER_AUTO_LIMIT")]
    assert any(p.amount == 26000 for p in resp.plan if p.action_type == "retrigger_payout")

    cdb.execute("UPDATE settlements SET amount = 25000 WHERE id = 'SET-96101'")
    cdb.commit()
    resp, retrigger = ask()
    assert retrigger == [("retrigger_payout", "ALLOW", "WITHIN_POLICY")]
    assert any(p.amount == 25000 for p in resp.plan if p.action_type == "retrigger_payout")


# ------------------------------------------------------------------ static guard: no cached DB reader sneaks in

def _cached_functions():
    found = {}
    for path in sorted((ROOT / "chaukas").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    name = ast.unparse(dec.func if isinstance(dec, ast.Call) else dec)
                    if name.split(".")[-1] in ("lru_cache", "cache", "cached_property"):
                        found[f"{path.relative_to(ROOT).as_posix()}::{node.name}"] = node
    return found


# the ONLY cached functions allowed: they read static YAML config, never money state
ALLOWED_CACHED = {
    "chaukas/integrations/_common.py::load_config",
    "chaukas/llm/client.py::config",
    "chaukas/privacy/pii.py::public_contacts",     # the published grievance contacts, from static YAML
}


def test_only_static_config_loaders_are_cached():
    assert set(_cached_functions()) == ALLOWED_CACHED, (
        "A new cached function appeared. Rule 4: money state is never cached. If it only reads static config, "
        "add it to ALLOWED_CACHED here after review.")


def test_no_cached_function_touches_the_database():
    db_words = {"connect", "execute", "executemany", "query", "query_one", "fetchone", "fetchall", "cursor"}
    for name, node in _cached_functions().items():
        called = {ast.unparse(n.func).split(".")[-1] for n in ast.walk(node) if isinstance(n, ast.Call)}
        assert not (called & db_words), f"{name} is cached but calls {called & db_words}"


def test_no_module_level_dict_or_list_is_used_as_a_money_cache():
    """Module-level containers whose name says cache / memo, anywhere in chaukas/."""
    hits = []
    for path in sorted((ROOT / "chaukas").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            for t in targets:
                if isinstance(t, ast.Name) and any(w in t.id.lower() for w in ("cache", "memo")):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}::{t.id}")
    assert hits == []
