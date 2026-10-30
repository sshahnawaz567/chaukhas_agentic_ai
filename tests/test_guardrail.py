"""One test per check + boundary trio (24,999 / 25,000 / 25,001), BLOCK-is-final, bait-and-switch,
split attack, audit + execution rules.

Owner: Member 2 · Contract: CONTRACTS C2
"""
import re
import sqlite3
from pathlib import Path

import pytest

from chaukas.agents import guardrail
from chaukas.core.models import Confirmation, ReasonCode, Verdict
from chaukas.observability import audit
from chaukas.policy import engine

ROOT = Path(__file__).resolve().parent.parent
A, B, N = Verdict.ALLOW, Verdict.BLOCK, Verdict.NEEDS_CONFIRMATION


@pytest.fixture
def run(db, make_state, make_step):
    """run(merchant, action, params, ...) -> Decision, using the test DB."""
    def go(merchant, action, params, step_no=1, session="S1", eligible=None, confirmation=None,
           reversible=True, policy=None, amount=None):
        state = make_state(merchant, session, eligible)
        step = make_step(action, params, step_no, amount, reversible)
        return guardrail.check(step, state, confirmation, conn=db, policy=policy)
    return go


def payout(settlement_id, amount):
    return {"settlement_id": settlement_id, "amount": amount}


def execute(db, decision, merchant, action, amount=None, step_no=1, session="S1"):
    """What the Action agent does after an ALLOW: pending row, then success."""
    key = f"{session}:{step_no}"
    audit.start_execution(db, idempotency_key=key, audit_id=decision.audit_id, trace_id=f"trace-{session}",
                          session_id=session, merchant_id=merchant, action_type=action, amount=amount)
    audit.finish_execution(db, key, "success", result_ref="REF-1")


def audit_row(db, audit_id):
    return db.execute("SELECT * FROM audit_log WHERE id = ?", (audit_id,)).fetchone()


# ------------------------------------------------------------------ contract hygiene

def test_reason_codes_equal_schema_check_list():
    sql = (ROOT / "data" / "schema.sql").read_text(encoding="utf-8")
    block = sql.split("reason_code        TEXT    NOT NULL CHECK (reason_code IN (")[1].split("))")[0]
    assert {c.value for c in ReasonCode} == set(re.findall(r"'([A-Z_]+)'", block))


# ------------------------------------------------------------------ checks 1-3: legality

def test_1_never_allowed_debit(run):
    d = run("M020", "debit_merchant_account", {"merchant_id": "M020", "amount": 5000}, amount=5000)
    assert (d.verdict, d.reason_code) == (B, ReasonCode.NEVER_ALLOWED)


def test_2_not_in_allow_list(run):
    d = run("M001", "send_email", {"to": "x"})
    assert (d.verdict, d.reason_code) == (B, ReasonCode.NOT_IN_ALLOW_LIST)


def test_2_kill_switch_disables_an_allowed_action(run, policy):
    policy["disabled_actions"] = ["raise_ticket"]
    d = run("M001", "raise_ticket", {"merchant_id": "M001", "issue": "x"}, policy=policy)
    assert (d.verdict, d.reason_code) == (B, ReasonCode.ACTION_DISABLED)


@pytest.mark.parametrize("params", [
    {"settlement_id": "SET-99213"},                                              # amount missing
    {"settlement_id": "SET-99213", "amount": "18400"},                           # string amount
    {"settlement_id": "SET-99213", "amount": 18400.0},                           # float amount
    {"settlement_id": "SET-99213", "amount": True},                              # bool is not rupees
    {"settlement_id": "SET-99213", "amount": 18400, "account_no": "999999999"},  # injected extra param
    {"settlement_id": "SET-51002", "amount": 32500},                             # another merchant's settlement
])
def test_3_invalid_params(run, params):
    d = run("M001", "retrigger_payout", params)
    assert (d.verdict, d.reason_code) == (B, ReasonCode.INVALID_PARAMS)


def test_3_step_amount_must_equal_params_amount(run):
    d = run("M001", "retrigger_payout", payout("SET-99213", 18400), amount=1)
    assert (d.verdict, d.reason_code) == (B, ReasonCode.INVALID_PARAMS)


def test_3_other_merchants_id_or_ticket(run):
    d1 = run("M001", "raise_ticket", {"merchant_id": "M002", "issue": "x"})
    d2 = run("M001", "update_ticket", {"ticket_id": "TKT-77201", "note": "hi"})   # M002's ticket
    assert (d1.reason_code, d2.reason_code) == (ReasonCode.INVALID_PARAMS,) * 2


# ------------------------------------------------------------------ checks 4-6: idempotency + ledger

def test_4_duplicate_action(db, run):
    d1 = run("M001", "retrigger_payout", payout("SET-99213", 18400))
    assert d1.verdict is A
    execute(db, d1, "M001", "retrigger_payout", 18400)
    d2 = run("M001", "retrigger_payout", payout("SET-99213", 18400))      # same session + step_no
    assert (d2.verdict, d2.reason_code) == (B, ReasonCode.DUPLICATE_ACTION)


def test_5_injection_amount_must_match_ledger(run):
    d = run("M005", "retrigger_payout", payout("SET-71209", 100000))      # demo scene 4
    assert (d.verdict, d.reason_code) == (B, ReasonCode.LEDGER_MISMATCH)
    assert "5600" in d.reason


def test_5_unknown_settlement(run):
    d = run("M001", "retrigger_payout", payout("SET-00000", 100))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.LEDGER_MISMATCH)


@pytest.mark.parametrize("merchant,settlement,amount", [
    ("M004", "SET-66120", 24800),   # pending (bank down): wait, do not retrigger
    ("M006", "SET-80120", 2400),    # KYC pending: never
    ("M013", "SET-97115", 3100),    # IFSC mismatch, bank details NOT updated
    ("M001", "SET-48219", 6200),    # already successful
])
def test_6_not_retriggerable(run, merchant, settlement, amount):
    d = run(merchant, "retrigger_payout", payout(settlement, amount))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.NOT_RETRIGGERABLE)


def test_6_already_retriggered_cannot_go_twice(db, run):
    db.execute("UPDATE settlements SET status = 'retriggered' WHERE id = 'SET-99213'")
    d = run("M001", "retrigger_payout", payout("SET-99213", 18400))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.NOT_RETRIGGERABLE)


# ------------------------------------------------------------------ checks 8-9: limits (boundary trio)

@pytest.mark.parametrize("merchant,settlement,amount,verdict,code", [
    ("M001", "SET-99213", 18400, A, ReasonCode.WITHIN_POLICY),
    ("M019", "SET-10488", 24999, A, ReasonCode.WITHIN_POLICY),             # 25,000 - 1
    ("M012", "SET-96101", 25000, A, ReasonCode.WITHIN_POLICY),             # exactly the limit: ALLOW
    ("M007", "SET-82150", 25001, N, ReasonCode.OVER_AUTO_LIMIT),           # limit + 1
    ("M002", "SET-51002", 32500, N, ReasonCode.OVER_AUTO_LIMIT),           # demo scene 2
    ("M009", "SET-90123", 26500, N, ReasonCode.OVER_AUTO_LIMIT),
])
def test_8_auto_limit_boundary(run, merchant, settlement, amount, verdict, code):
    d = run(merchant, "retrigger_payout", payout(settlement, amount))
    assert (d.verdict, d.reason_code) == (verdict, code)
    if verdict is N:
        assert d.confirmation_kind == "step_up" and "auto_limit 25000" in d.reason


def test_9_split_attack_daily_limit(db, run):
    d1 = run("M014", "retrigger_payout", payout("SET-98101", 15000), step_no=1)
    assert d1.verdict is A
    execute(db, d1, "M014", "retrigger_payout", 15000, step_no=1)
    d2 = run("M014", "retrigger_payout", payout("SET-98102", 14000), step_no=2)   # 15000 + 14000 > 25000
    assert (d2.verdict, d2.reason_code) == (N, ReasonCode.OVER_DAILY_LIMIT)
    assert "today_total 15000" in d2.reason


def test_9_failed_execution_does_not_count_towards_daily_limit(db, run):
    d1 = run("M014", "retrigger_payout", payout("SET-98101", 15000), step_no=1)
    audit.start_execution(db, idempotency_key="S1:1", audit_id=d1.audit_id, trace_id="t", session_id="S1",
                          merchant_id="M014", action_type="retrigger_payout", amount=15000)
    audit.finish_execution(db, "S1:1", "failed", error="bank error")
    d2 = run("M014", "retrigger_payout", payout("SET-98102", 14000), step_no=2)
    assert d2.verdict is A


# ------------------------------------------------------------------ check 7 + 10: offers

def test_7_ineligible_merchant(run):
    d = run("M003", "create_offer", {"merchant_id": "M003", "amount": 20000}, eligible=(False, 0))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.OFFER_NOT_ELIGIBLE)


def test_7_no_lender_answer_fails_closed(run):
    d = run("M010", "create_offer", {"merchant_id": "M010", "amount": 50000})      # state has no eligibility
    assert (d.verdict, d.reason_code) == (B, ReasonCode.OFFER_NOT_ELIGIBLE)


def test_7_amount_above_lender_max(run):
    d = run("M010", "create_offer", {"merchant_id": "M010", "amount": 175001}, eligible=(True, 175000))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.OFFER_NOT_ELIGIBLE)


def test_7_cooling_off_after_decline(run):
    d = run("M018", "create_offer", {"merchant_id": "M018", "amount": 55000}, eligible=(True, 55000))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.OFFER_COOLING_OFF)


def test_7_issue_still_failed_blocks_offer(run):
    d = run("M001", "create_offer", {"merchant_id": "M001", "amount": 50000}, eligible=(True, 50000))
    assert (d.verdict, d.reason_code) == (B, ReasonCode.ISSUE_UNRESOLVED)


def test_7_kyc_pending_and_open_handoff_block_offer(db, run):
    db.execute("UPDATE merchants SET kyc_status = 'pending' WHERE merchant_id = 'M010'")
    d1 = run("M010", "create_offer", {"merchant_id": "M010", "amount": 50000}, eligible=(True, 175000))
    assert (d1.verdict, d1.reason_code) == (B, ReasonCode.ISSUE_UNRESOLVED)

    db.execute("UPDATE merchants SET kyc_status = 'verified' WHERE merchant_id = 'M010'")
    db.execute("INSERT INTO sessions (session_id, merchant_id) VALUES ('S9', 'M010')")
    db.execute("INSERT INTO handoffs (id, session_id, merchant_id, trace_id, reason_code, brief_json, "
               "decision_needed) VALUES ('HO-1','S9','M010','t','LOW_CONFIDENCE','{}','x')")
    d2 = run("M010", "create_offer", {"merchant_id": "M010", "amount": 50000}, eligible=(True, 175000))
    assert (d2.verdict, d2.reason_code) == (B, ReasonCode.ISSUE_UNRESOLVED)


def test_7_pending_settlement_needs_an_actioned_ticket(db, run):
    offer = {"merchant_id": "M015", "amount": 20000}
    d0 = run("M015", "create_offer", offer, step_no=1, eligible=(True, 30000))
    assert (d0.verdict, d0.reason_code) == (B, ReasonCode.ISSUE_UNRESOLVED)

    t = run("M015", "raise_ticket", {"merchant_id": "M015", "issue": "pending", "settlement_id": "SET-99120"},
            step_no=2)
    assert t.verdict is A
    execute(db, t, "M015", "raise_ticket", step_no=2)
    d1 = run("M015", "create_offer", offer, step_no=3, eligible=(True, 30000))
    assert (d1.verdict, d1.reason_code) == (N, ReasonCode.CONSENT_REQUIRED)


def test_10_offer_always_needs_consent_then_merchant_confirms(db, run):
    offer = {"merchant_id": "M010", "amount": 50000}
    d1 = run("M010", "create_offer", offer, step_no=1, eligible=(True, 175000))
    assert (d1.verdict, d1.reason_code, d1.confirmation_kind) == (N, ReasonCode.CONSENT_REQUIRED, "consent")

    c = Confirmation(pending_audit_id=d1.audit_id, actor="merchant", kind="consent")
    d2 = run("M010", "create_offer", offer, step_no=1, eligible=(True, 175000), confirmation=c)
    assert (d2.verdict, d2.reason_code) == (A, ReasonCode.CONFIRMED_BY_MERCHANT)
    row = audit_row(db, d2.audit_id)
    assert row["confirms_audit_id"] == d1.audit_id and row["actor"] == "merchant"


def test_10_irreversible_step_needs_consent(run):
    d = run("M001", "raise_ticket", {"merchant_id": "M001", "issue": "x"}, reversible=False)
    assert (d.verdict, d.reason_code) == (N, ReasonCode.CONSENT_REQUIRED)


# ------------------------------------------------------------------ confirmations

def over_limit(run, **kw):
    return run("M002", "retrigger_payout", payout("SET-51002", 32500), **kw)


def test_step_up_with_correct_otp_allows(db, run, mock_otp):
    d1 = over_limit(run)
    c = Confirmation(pending_audit_id=d1.audit_id, actor="merchant", kind="step_up", otp=mock_otp)
    d2 = over_limit(run, confirmation=c)
    assert (d2.verdict, d2.reason_code) == (A, ReasonCode.CONFIRMED_BY_MERCHANT)
    assert d2.rollback_token and audit_row(db, d2.audit_id)["confirms_audit_id"] == d1.audit_id


@pytest.mark.parametrize("kind,otp", [("step_up", "000000"), ("step_up", None), ("consent", None)])
def test_step_up_with_wrong_otp_or_kind_stays_pending(run, kind, otp):
    d1 = over_limit(run)
    c = Confirmation(pending_audit_id=d1.audit_id, actor="merchant", kind=kind, otp=otp)
    d2 = over_limit(run, confirmation=c)
    assert (d2.verdict, d2.reason_code) == (N, ReasonCode.OVER_AUTO_LIMIT)
    assert "confirmation ignored" in d2.reason


def test_human_approval_gives_approved_by_human(db, run):
    d1 = over_limit(run)
    c = Confirmation(pending_audit_id=d1.audit_id, actor="human", actor_id="STAFF-7", kind="step_up")
    d2 = over_limit(run, confirmation=c)
    assert (d2.verdict, d2.reason_code) == (A, ReasonCode.APPROVED_BY_HUMAN)
    assert audit_row(db, d2.audit_id)["actor"] == "human"


def test_human_approval_needs_a_staff_id(run):
    d1 = over_limit(run)
    c = Confirmation(pending_audit_id=d1.audit_id, actor="human", kind="step_up")
    assert over_limit(run, confirmation=c).verdict is N


def test_block_is_final_even_with_human_approval(run):
    """M013's IFSC is not fixed: no confirmation of any kind can turn this BLOCK into an ALLOW."""
    pending = over_limit(run)
    c = Confirmation(pending_audit_id=pending.audit_id, actor="human", actor_id="STAFF-7", kind="step_up")
    d = run("M013", "retrigger_payout", payout("SET-97115", 3100), confirmation=c)
    assert (d.verdict, d.reason_code) == (B, ReasonCode.NOT_RETRIGGERABLE)

    d = run("M005", "retrigger_payout", payout("SET-71209", 100000), confirmation=c)
    assert d.verdict is B


def test_bait_and_switch_confirmation_does_not_transfer(run):
    """Consent for a 50,000 offer must not unlock a 60,000 offer."""
    d1 = run("M010", "create_offer", {"merchant_id": "M010", "amount": 50000}, eligible=(True, 175000))
    c = Confirmation(pending_audit_id=d1.audit_id, actor="merchant", kind="consent")
    d2 = run("M010", "create_offer", {"merchant_id": "M010", "amount": 60000}, eligible=(True, 175000),
             confirmation=c)
    assert (d2.verdict, d2.reason_code) == (N, ReasonCode.CONSENT_REQUIRED)
    assert "differs" in d2.reason


def test_bait_and_switch_with_same_amount_but_different_params(run):
    """Amount is identical (None); only the ticket text differs. The params check alone must catch it."""
    first = {"merchant_id": "M001", "issue": "QR band hai"}
    d1 = run("M001", "raise_ticket", first, reversible=False)
    c = Confirmation(pending_audit_id=d1.audit_id, actor="merchant", kind="consent")
    d2 = run("M001", "raise_ticket", {"merchant_id": "M001", "issue": "kuch aur"}, reversible=False,
             confirmation=c)
    assert (d2.verdict, d2.reason_code) == (N, ReasonCode.CONSENT_REQUIRED) and "differs" in d2.reason
    d3 = run("M001", "raise_ticket", first, step_no=2, reversible=False, confirmation=c)   # identical step: fine
    assert d3.verdict is A


def test_confirmation_can_be_used_only_once(run):
    offer = {"merchant_id": "M010", "amount": 50000}
    d1 = run("M010", "create_offer", offer, step_no=1, eligible=(True, 175000))
    c = Confirmation(pending_audit_id=d1.audit_id, actor="merchant", kind="consent")
    assert run("M010", "create_offer", offer, step_no=1, eligible=(True, 175000), confirmation=c).verdict is A
    d3 = run("M010", "create_offer", offer, step_no=2, eligible=(True, 175000), confirmation=c)
    assert d3.verdict is N and "already used" in d3.reason


def test_confirmation_from_another_session_is_rejected(run):
    d1 = over_limit(run, session="S1")
    c = Confirmation(pending_audit_id=d1.audit_id, actor="human", actor_id="STAFF-7", kind="step_up")
    assert over_limit(run, session="S2", confirmation=c).verdict is N


# ------------------------------------------------------------------ audit + executions

def test_read_only_allowed_is_not_audited(db, run):
    d = run("M001", "verify_ledger", {"settlement_id": "SET-99213"})
    assert d.verdict is A and d.audit_id is None and d.rollback_token is None
    assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_blocked_read_only_is_audited(db, run):
    d = run("M001", "verify_ledger", {"settlement_id": "SET-51002"})       # M002's settlement
    assert d.verdict is B and d.audit_id is not None


def test_one_audit_row_per_write_and_token_only_on_allow(db, run):
    allow = run("M001", "retrigger_payout", payout("SET-99213", 18400), step_no=1)
    needs = over_limit(run, step_no=2)
    block = run("M005", "retrigger_payout", payout("SET-71209", 100000), step_no=3)
    assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 3
    assert allow.rollback_token and not needs.rollback_token and not block.rollback_token
    assert audit_row(db, needs.audit_id)["guardrail_decision"] == "NEEDS_CONFIRMATION"


def test_redteam_actor_is_recorded_as_system(db, make_state, make_step):
    step = make_step("debit_merchant_account", {"merchant_id": "M020", "amount": 5000})
    d = guardrail.check(step, make_state("M020"), conn=db, actor="system")
    assert audit_row(db, d.audit_id)["actor"] == "system"


def test_audit_params_are_scrubbed(db, run):
    d = run("M001", "raise_ticket", {"merchant_id": "M001", "issue": "mera phone +919800000001 aur pan ABAPS1037H"})
    stored = audit_row(db, d.audit_id)["params_masked"]
    assert "9800000001" not in stored and "ABAPS1037H" not in stored and "XXXXXX0001" in stored


def test_audit_log_is_append_only(db, run):
    d = run("M001", "retrigger_payout", payout("SET-99213", 18400))
    for sql in ("UPDATE audit_log SET amount = 1", "DELETE FROM audit_log"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute(sql)
    assert audit_row(db, d.audit_id)["amount"] == 18400


def test_executions_refuse_a_non_allow_decision(db, run):
    block = run("M005", "retrigger_payout", payout("SET-71209", 100000))
    with pytest.raises(sqlite3.DatabaseError, match="requires an ALLOW"):
        audit.start_execution(db, idempotency_key="S1:1", audit_id=block.audit_id, trace_id="t", session_id="S1",
                              merchant_id="M005", action_type="retrigger_payout", amount=100000)


def test_execution_status_transitions(db, run):
    d = run("M001", "retrigger_payout", payout("SET-99213", 18400))
    execute(db, d, "M001", "retrigger_payout", 18400)
    audit.finish_execution(db, "S1:1", "rolled_back")
    with pytest.raises(ValueError):
        audit.finish_execution(db, "S1:1", "success")


# ------------------------------------------------------------------ never cached, always deterministic

def test_money_state_is_read_fresh_every_call(db, run):
    assert run("M001", "retrigger_payout", payout("SET-99213", 18400), step_no=1).verdict is A
    db.execute("UPDATE settlements SET status = 'success', cause = NULL WHERE id = 'SET-99213'")
    d = run("M001", "retrigger_payout", payout("SET-99213", 18400), step_no=2)
    assert (d.verdict, d.reason_code) == (B, ReasonCode.NOT_RETRIGGERABLE)


def test_same_input_same_decision(db, make_state, make_step):
    step, state = make_step("retrigger_payout", payout("SET-51002", 32500)), make_state("M002")
    first = engine.evaluate(step, state, db, engine.load_policy())
    second = engine.evaluate(step, state, db, engine.load_policy())
    assert first == second


def test_guardrail_has_no_llm_imports():
    """Rule 1: the guardrail is plain Python. No LLM client may be imported by it or the engine."""
    for f in ("chaukas/agents/guardrail.py", "chaukas/policy/engine.py", "chaukas/observability/audit.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(openai|chaukas\.llm|langchain|langgraph|anthropic)", src, re.M)
