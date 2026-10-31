"""Short-term credit line (Postpaid-style): simulated lender formula, plan, orchestrator flow end to end
with Member 2's REAL guardrail, reply templates. No network: LLM calls fall back to keyword / templates.

Owner: Member 1 · Contract: CONTRACTS C3 (lending), C1 (plans/orchestrator)
"""
import json

import pytest

from chaukas import db
from chaukas.agents import reply as reply_agent
from chaukas.core import m2_shim, orchestrator
from chaukas.core.models import TurnStatus
from chaukas.gateway import session as gw
from chaukas.integrations import lending
from data.seed import seed

CREDIT_ASK = "Postpaid credit line mil sakti hai kya?"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    path = tmp_path / "credit.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    monkeypatch.setenv("CHAUKAS_REPLAY_MODE", "off")
    monkeypatch.setenv("CHAUKAS_AGENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr("chaukas.llm.client._client", lambda provider: None)  # no network, ever
    monkeypatch.setattr(m2_shim, "emit_span", lambda span: None)
    yield path


def rows(sql, *args):
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def session(merchant_id):
    return gw.create_session(merchant_id, "chat", "autonomous")["session_id"]


# ------------------------------------------------------------------ the simulated lender
@pytest.mark.parametrize("merchant,limit", [
    ("M016", 7000),    # term loan: not eligible (account 8 months) -> credit line 7,000
    ("M008", 8000),    # term loan: not eligible (balance 15k) -> credit line 8,000
    ("M001", 19000),   # both
    ("M002", 50000),   # capped
])
def test_credit_line_limit_formula(merchant, limit):
    d = lending.check_credit_line(merchant)
    assert (d.eligible, d.max_amount, d.product) == (True, limit, "credit_line")
    assert type(d.max_amount) is int


@pytest.mark.parametrize("merchant,code", [
    ("M003", "LIMIT_TOO_SMALL"),   # passes the rules but 4,000 < min 5,000
    ("M006", "ACCOUNT_TOO_NEW"),
    ("M020", "AVG_BALANCE_LOW"),
])
def test_credit_line_not_eligible(merchant, code):
    d = lending.check_credit_line(merchant)
    assert (d.eligible, d.max_amount) == (False, 0) and code in d.reason_codes


def test_check_eligibility_default_is_still_the_term_loan():
    assert lending.check_eligibility("M016").product == "term_loan"
    assert lending.check_eligibility("M016", "credit_line") == lending.check_credit_line("M016")


def test_credit_line_kfs_has_cycle_free_days_and_late_fee():
    k = lending.build_kfs("M016", 7000, "credit_line")
    assert k.product == "credit_line" and k.tenure_months == 1 and k.total_repayable_inr == 7000
    assert (k.billing_cycle_days, k.interest_free_days, k.late_fee_inr) == (30, 30, 250)
    assert lending.build_kfs("M001", 50000).product == "term_loan"  # term loan KFS unchanged


@pytest.mark.parametrize("text,wanted", [
    (CREDIT_ASK, True), ("Stock ke liye udhaar chahiye", True), ("मुझे उधार चाहिए", True),
    ("Can I get a credit line?", True), ("Mujhe 20 hazaar ka loan chahiye", False), ("Can I get a loan?", False),
])
def test_wants_credit_line_only_on_the_merchants_own_words(text, wanted):
    assert lending.wants_credit_line(text) is wanted


# ------------------------------------------------------------------ end to end, REAL guardrail
def test_credit_line_offered_with_kfs_then_accepted():
    sid = session("M016")
    r1 = orchestrator.handle_message(sid, CREDIT_ASK)
    assert r1.intent.value == "loan_inquiry" and r1.status == TurnStatus.AWAITING_CONFIRMATION
    assert [(p.action_type, p.params.get("product")) for p in r1.plan] == [
        ("check_eligibility", "credit_line"), ("create_offer", "credit_line")]
    pc = r1.pending_confirmation
    assert pc["product"] == "credit_line" and pc["step"]["amount"] == 7000
    assert pc["kfs"]["interest_free_days"] == 30 and pc["kfs"]["late_fee_inr"] == 250
    assert "7,000" in r1.reply and "credit line" in r1.reply.lower()
    assert not rows("SELECT * FROM offers WHERE merchant_id='M016'")  # nothing before consent
    # the guardrail saw (and audited) the product
    audit = rows("SELECT params_masked, guardrail_decision FROM audit_log WHERE action_type='create_offer'")
    assert json.loads(audit[0]["params_masked"])["product"] == "credit_line"

    r2 = orchestrator.handle_message(sid, "haan")
    assert r2.status == TurnStatus.COMPLETED and r2.decisions[-1]["reason_code"] == "CONFIRMED_BY_MERCHANT"
    offer = rows("SELECT * FROM offers WHERE merchant_id='M016'")[0]
    assert offer["status"] == "accepted" and offer["amount"] == 7000 and offer["kfs_shown_at"]
    assert json.loads(offer["kfs_json"])["product"] == "credit_line"
    assert r2.handoff.reason_code == "LOAN_ACCEPTED" and r2.handoff.loan.product == "credit_line"
    assert r2.handoff.loan.interest_free_days == 30 and "credit line" in r2.handoff.asked


def test_plain_loan_ask_is_unchanged_no_credit_line():
    r = orchestrator.handle_message(session("M016"), "Can I get a loan for my shop?")
    assert [p.action_type for p in r.plan] == ["check_eligibility"] and "product" not in r.plan[0].params
    assert r.status == TurnStatus.COMPLETED and not rows("SELECT * FROM offers WHERE merchant_id='M016'")


def test_credit_line_ask_from_an_ineligible_merchant_is_an_honest_no():
    r = orchestrator.handle_message(session("M003"), "Stock ke liye udhaar chahiye bhai")
    assert [p.action_type for p in r.plan] == ["check_eligibility"] and r.status == TurnStatus.COMPLETED
    assert "credit line" in r.reply.lower() and not rows("SELECT * FROM offers WHERE merchant_id='M003'")


def test_declined_credit_line_is_recorded_as_declined_credit_line():
    sid = session("M016")
    orchestrator.handle_message(sid, CREDIT_ASK)
    r = orchestrator.handle_message(sid, "nahi")
    assert r.status == TurnStatus.COMPLETED
    row = rows("SELECT status, kfs_json FROM offers WHERE merchant_id='M016'")[0]
    assert row["status"] == "declined" and json.loads(row["kfs_json"])["product"] == "credit_line"


def test_credit_line_ask_from_term_loan_eligible_merchant_offers_the_credit_line():
    """The merchant asked for a credit line: offer what was asked, capped by the credit-line answer."""
    r = orchestrator.handle_message(session("M010"), "Mujhe postpaid udhaar chahiye")
    offer = r.pending_confirmation["step"]
    assert offer["params"]["product"] == "credit_line" and offer["amount"] == lending.check_credit_line("M010").max_amount


# ------------------------------------------------------------------ templates
def test_every_reply_language_has_the_credit_line_templates():
    import yaml
    data = yaml.safe_load((db.ROOT / "config" / "fallback_replies.yaml").read_text(encoding="utf-8"))
    for lang, t in data.items():
        for key in ("credit_line_offer", "credit_line_accepted", "credit_line_not_eligible"):
            assert key in t, (lang, key)
        t["credit_line_offer"].format(amount="7,000", lender_name="L", free_days=30, apr_pct=24.0,
                                      late_fee="250", grievance="g")
        t["credit_line_accepted"].format(amount="7,000", offer_id="OFF-1")
    assert reply_agent.template_line("hi-Latn", "credit_line_not_eligible").startswith("Abhi aap credit line")
