"""Fairness (RBI FREE-AI): same cashflow features with a different name / preferred_lang /
device must give an identical lender decision. Lender may use ONLY cashflow features.

Owner: Member 2 · COMPLIANCE.md R6

Three layers: (1) the code itself only reads cashflow_features, (2) counterfactuals: change who the merchant
is and nothing else, (3) the guardrail's offer gating does not react to who the merchant is either.
KYC status is NOT varied: it is a legal gating condition (offer_gating), not a personal attribute.
"""
import inspect
import json
import re

import pytest

from chaukas.agents import guardrail
from chaukas.core.models import LenderDecision
from chaukas.db import connect
from chaukas.integrations import lending
from chaukas.policy import engine
from data.seed import seed

FIXTURES = json.loads((lending.db.ROOT / "data" / "merchant_fixtures.json").read_text(encoding="utf-8"))["merchants"]
IDS = [m["merchant_id"] for m in FIXTURES]

NAMES = ["Aarav Kumar", "Fatima Begum", "Lakshmi Iyer", "Gurpreet Singh", "Mary D'Souza", "Zoya Khan"]
LANGS = ["hi-IN", "en-IN", "ta-IN", "te-IN", "mr-IN", "ml-IN", "gu-IN", "bn-IN", "pa-IN"]
DEVICES = ["soundbox", "pos", "qr", "app", None]
FEATURE_COLUMNS = ["txn_count_30d", "withdrawals_30d", "inflow_30d", "outflow_30d", "avg_balance",
                   "active_days_30d", "inflow_cv", "account_age_months"]
ALLOWED_REASON_CODES = {"AVG_BALANCE_OK", "AVG_BALANCE_LOW", "ACCOUNT_AGE_OK", "ACCOUNT_TOO_NEW", "INFLOW_STEADY",
                        "INFLOW_VOLATILE", "ACTIVE_DAYS_OK", "ACTIVE_DAYS_LOW"}


@pytest.fixture
def fdb(tmp_path, monkeypatch):
    path = tmp_path / "fair.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    conn = connect(path)
    yield conn
    conn.close()


def decide(merchant_id) -> dict:
    return lending.check_eligibility(merchant_id).model_dump()


def set_identity(conn, merchant_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE merchants SET {cols} WHERE merchant_id = ?", (*fields.values(), merchant_id))
    conn.commit()


# ------------------------------------------------------------------ (1) the code only looks at cashflow features

def test_the_lender_query_reads_only_the_cashflow_table():
    src = inspect.getsource(lending.check_eligibility)
    assert "FROM cashflow_features" in src
    assert not re.search(r"\bmerchants\b", src.replace("merchant_id", ""))
    for forbidden in ("name", "preferred_lang", "device", "phone", "vpa", "pan", "gender", "religion", "caste",
                      "location", "city", "pincode", "kyc_status"):
        assert not re.search(rf"\b{forbidden}\b", src), f"check_eligibility mentions {forbidden!r}"


def test_the_lender_returns_only_cashflow_reason_codes(fdb):
    for mid in IDS:
        assert set(decide(mid)["reason_codes"]) <= ALLOWED_REASON_CODES


def test_the_simulated_lender_matches_the_fixture_oracle_for_all_merchants(fdb):
    for m in FIXTURES:
        assert LenderDecision(**decide(m["merchant_id"])) == LenderDecision(**m["expected_loan_eligibility"]), m["merchant_id"]


# ------------------------------------------------------------------ (2) counterfactuals

@pytest.mark.parametrize("field,values", [("name", NAMES), ("preferred_lang", LANGS), ("device", DEVICES)])
def test_changing_who_the_merchant_is_never_changes_the_decision(fdb, field, values):
    for mid in IDS:
        baseline = decide(mid)
        for value in values:
            set_identity(fdb, mid, **{field: value})
            assert decide(mid) == baseline, f"{mid}: {field}={value!r} changed the lender decision"


def test_everything_about_the_person_changed_at_once_still_gives_the_same_answer(fdb):
    for mid in IDS:
        baseline = decide(mid)
        set_identity(fdb, mid, name="Someone Else", preferred_lang="ta-IN", device="qr", phone="+919999999999",
                     vpa="someoneelse@paytm", pan="ZZZZZ9999Z", account_no="999999999999", ifsc="HDFC0009999")
        assert decide(mid) == baseline


def test_two_different_people_with_identical_cashflow_get_identical_decisions(fdb):
    """Give an ineligible merchant (M003, ta-IN) the features of an eligible one (M001, hi-IN): the decision follows
    the features, not the person."""
    features = fdb.execute(f"SELECT {', '.join(FEATURE_COLUMNS)} FROM cashflow_features WHERE merchant_id = 'M001'").fetchone()
    assert decide("M003") != decide("M001")
    fdb.execute(f"UPDATE cashflow_features SET {', '.join(c + ' = ?' for c in FEATURE_COLUMNS)} WHERE merchant_id = 'M003'",
                tuple(features))
    fdb.commit()
    assert decide("M003") == decide("M001")


def test_only_the_cashflow_features_move_the_decision(fdb):
    """The other direction: change one feature and the decision does change (so the tests above are not vacuous)."""
    before = decide("M003")
    assert before["eligible"] is False and "AVG_BALANCE_LOW" in before["reason_codes"]
    fdb.execute("UPDATE cashflow_features SET avg_balance = 90000 WHERE merchant_id = 'M003'")
    fdb.commit()
    assert decide("M003")["reason_codes"] != before["reason_codes"]


# ------------------------------------------------------------------ (3) the guardrail's offer gating

def _offer_decision(conn, make_state, make_step, mid):
    lender = lending.check_eligibility(mid)
    step = make_step("create_offer", {"merchant_id": mid, "amount": lender.max_amount or 5000},
                     amount=lender.max_amount or 5000)
    state = make_state(mid, eligible=(lender.eligible, lender.max_amount))
    d = guardrail.check(step, state, None, conn=conn, policy=engine.load_policy())
    return d.verdict.value, d.reason_code.value


@pytest.mark.parametrize("field,values", [("name", NAMES[:3]), ("preferred_lang", LANGS), ("device", DEVICES)])
def test_the_guardrail_gives_the_same_offer_decision_whoever_the_merchant_is(fdb, make_state, make_step, field, values):
    for mid in ("M001", "M003", "M010", "M018"):          # eligible, ineligible, eligible, cooling-off
        baseline = _offer_decision(fdb, make_state, make_step, mid)
        for value in values:
            set_identity(fdb, mid, **{field: value})
            assert _offer_decision(fdb, make_state, make_step, mid) == baseline, f"{mid}: {field}={value!r}"


# ------------------------------------------------------------------ the same three layers for the credit line

def decide_credit(merchant_id) -> dict:
    return lending.check_credit_line(merchant_id).model_dump()


def test_the_credit_line_query_reads_only_the_cashflow_table():
    src = inspect.getsource(lending.check_credit_line)
    assert "FROM cashflow_features" in src
    assert not re.search(r"\bmerchants\b", src.replace("merchant_id", ""))
    for forbidden in ("name", "preferred_lang", "device", "phone", "vpa", "pan", "gender", "religion", "caste",
                      "location", "city", "pincode", "kyc_status"):
        assert not re.search(rf"\b{forbidden}\b", src), f"check_credit_line mentions {forbidden!r}"


def test_the_credit_line_returns_only_cashflow_reason_codes(fdb):
    for mid in IDS:
        assert set(decide_credit(mid)["reason_codes"]) <= ALLOWED_REASON_CODES | {"LIMIT_TOO_SMALL"}


@pytest.mark.parametrize("field,values", [("name", NAMES), ("preferred_lang", LANGS), ("device", DEVICES)])
def test_changing_who_the_merchant_is_never_changes_the_credit_line(fdb, field, values):
    for mid in IDS:
        baseline = decide_credit(mid)
        for value in values:
            set_identity(fdb, mid, **{field: value})
            assert decide_credit(mid) == baseline, f"{mid}: {field}={value!r}"
