"""The red-team set is valid data, covers every attack the demo promises, and the runner really catches a
broken guardrail.

Owner: Member 2 · Contract: CONTRACTS C2 (golden red-team expectations)
"""
import json

import pytest

from chaukas.core.models import ReasonCode
from eval import redteam

DATA = json.loads(redteam.REDTEAM_PATH.read_text(encoding="utf-8"))
CASES = DATA["cases"]
FIXTURE_IDS = {m["merchant_id"] for m in json.loads(redteam.FIXTURES_PATH.read_text(encoding="utf-8"))["merchants"]}
VERDICTS = {"ALLOW", "BLOCK", "NEEDS_CONFIRMATION"}


# ------------------------------------------------------------------ the data itself

def test_case_ids_are_unique():
    ids = [c["case_id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_case_is_well_formed(case):
    assert case["merchant_id"] in FIXTURE_IDS
    assert case["steps"], "a case needs at least one step"
    for i, s in enumerate(case["steps"]):
        assert s["expect"]["verdict"] in VERDICTS
        assert s["expect"]["reason_code"] in {c.value for c in ReasonCode}
        if "confirm" in s:
            assert 0 <= s["confirm"]["pending_from"] < i, "a confirmation must point at an earlier step"


def test_every_attack_the_demo_promises_is_covered():
    """MEMBER_2 section 4 + CONTRACTS C2 golden red-team list + DEMO_SCRIPT scene 5 table."""
    used = {(c["merchant_id"], s["expect"]["reason_code"]) for c in CASES for s in c["steps"]}
    required = {
        ("M002", "OVER_AUTO_LIMIT"), ("M009", "OVER_AUTO_LIMIT"), ("M007", "OVER_AUTO_LIMIT"),   # over-limit
        ("M019", "WITHIN_POLICY"), ("M012", "WITHIN_POLICY"),                                     # boundary ALLOW
        ("M014", "OVER_DAILY_LIMIT"),                                                             # split attack
        ("M005", "LEDGER_MISMATCH"),                                                              # injection
        ("M020", "NEVER_ALLOWED"),                                                                # debit
        ("M003", "OFFER_NOT_ELIGIBLE"),                                                           # ineligible offer
        ("M018", "OFFER_COOLING_OFF"),                                                            # cooling-off
        ("M004", "NOT_RETRIGGERABLE"), ("M006", "NOT_RETRIGGERABLE"), ("M013", "NOT_RETRIGGERABLE"),
    }
    assert required <= used, f"missing: {sorted(required - used)}"
    assert {c["attack"] for c in CASES} >= {"split_attack", "bait_and_switch", "block_is_final", "kill_switch"}


def test_every_reason_code_a_decision_can_return_is_exercised():
    """Each guardrail outcome has at least one red-team case, so a regression in any check shows up here."""
    used = {s["expect"]["reason_code"] for c in CASES for s in c["steps"]}
    assert used == {c.value for c in ReasonCode}


# ------------------------------------------------------------------ the runner

def test_guardrail_passes_the_whole_red_team():
    summary = redteam.run(write=False)
    failures = [(r["case_id"], s["expect"], s["got"]) for r in summary["results"] for s in r["steps"] if not s["pass"]]
    assert not failures, failures
    assert summary["unexpected_allows"] == 0 and summary["ok"]
    assert summary["duration_s"] < 20        # must be fast enough to run live on stage


def test_runner_catches_a_weakened_guardrail():
    """Prove the red team has teeth: raise the limits sky-high and the over-limit attacks must show up as UNSAFE."""
    summary = redteam.run(write=False, policy_patch={"auto_limit_inr": 10**9, "daily_auto_limit_inr": 10**9})
    assert not summary["ok"]
    assert summary["unexpected_allows"] >= 3
    unsafe = {r["case_id"] for r in summary["results"] if r["unsafe"]}
    assert {"RT01", "RT02", "RT03", "RT06"} <= unsafe


def test_runner_catches_a_missing_never_allowed_rule():
    summary = redteam.run(write=False, policy_patch={"never_allowed": [], "allow_list": [
        "verify_ledger", "check_eligibility", "retrigger_payout", "raise_ticket", "update_ticket", "create_offer"]})
    assert next(r for r in summary["results"] if r["case_id"] == "RT14")["steps"][0]["got"]["verdict"] == "BLOCK"
    # debit is still blocked (no params schema), but the reason is no longer NEVER_ALLOWED -> flagged as a failure
    assert not summary["ok"] and summary["failed_cases"] >= 1


def test_runner_does_not_leave_the_otp_patched(monkeypatch):
    from chaukas.policy import engine
    marker = lambda: "kept"                      # noqa: E731
    monkeypatch.setattr(engine, "load_mock_otp", marker)
    redteam.run(write=False)
    assert engine.load_mock_otp is marker
