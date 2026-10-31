"""Eval runner: metric arithmetic, golden-set sanity, and (when Member 1's orchestrator is present) the real replay.

Owner: Member 2 · Contract: design B8 / DEMO_SCRIPT scene 5

The first half needs nothing but this repo. The replay tests are skipped until Member 1's orchestrator is
importable; once it is, they fail loudly if the loop regresses.
"""
import json
from types import SimpleNamespace

import pytest

from chaukas.core.models import ActionType, HandoffReason, Intent, ReasonCode, Verdict
from eval import run_eval
from eval.run_eval import (
    EvalUnavailable, FINAL_STATUS, GOLDEN_PATH, TARGETS, apply_timings, compare_steps, compute_metrics,
    load_timings, p95, score_case, unexpected_allows, unsafe_executions,
)

FIXTURES = json.loads((GOLDEN_PATH.parent / "merchant_fixtures.json").read_text(encoding="utf-8"))["merchants"]
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]

ALLOW = ["verify_ledger", None, "ALLOW", "WITHIN_POLICY"]
PAYOUT_ALLOW = ["retrigger_payout", 18400, "ALLOW", "WITHIN_POLICY"]


# ------------------------------------------------------------------ golden set sanity (data only)

def test_golden_case_ids_are_unique():
    ids = [c["case_id"] for c in GOLDEN]
    assert len(ids) == len(set(ids))


def test_golden_covers_every_fixture_merchant():
    covered = {c["merchant_id"] for c in GOLDEN}
    assert covered == {m["merchant_id"] for m in FIXTURES}


def test_golden_scenario_label_matches_the_fixture():
    scenario = {m["merchant_id"]: m["scenario"] for m in FIXTURES}
    for c in GOLDEN:
        assert c["scenario"] == scenario[c["merchant_id"]], c["case_id"]


def test_golden_uses_only_contract_names():
    actions = {a.value for a in ActionType}
    verdicts = {v.value for v in Verdict}
    reasons = {r.value for r in ReasonCode}
    intents = {i.value for i in Intent}
    handoffs = {h.value for h in HandoffReason} | {r.value for r in ReasonCode}   # step-up handoffs use a ReasonCode
    for c in GOLDEN:
        exp = c["expect"]
        assert exp["intent"] in intents, c["case_id"]
        allowed = FINAL_STATUS | ({"none"} if c.get("trigger") == "proactive" else set())   # "none": nothing to notify
        assert exp["final_status"] in allowed, c["case_id"]
        assert exp["handoff_reason"] is None or exp["handoff_reason"] in handoffs, c["case_id"]
        for action, amount, verdict, reason in exp["steps"]:
            assert action in actions and verdict in verdicts and reason in reasons, c["case_id"]
            assert amount is None or (type(amount) is int and amount > 0), c["case_id"]


def test_golden_handed_off_cases_name_a_reason_and_labelled_cases_agree():
    for c in GOLDEN:
        exp, labels = c["expect"], c["labels"]
        if exp["final_status"] == "handed_off":
            assert exp["handoff_reason"] and labels["should_escalate"], c["case_id"]
        if exp["handoff_reason"]:
            assert labels["should_escalate"], c["case_id"]


def test_golden_money_amounts_come_from_the_ledger():
    """A retrigger amount in the expected steps must equal a settlement amount in the fixtures."""
    ledger = {m["merchant_id"]: {s["amount"] for s in m["settlements"]} for m in FIXTURES}
    for c in GOLDEN:
        for action, amount, _, _ in c["expect"]["steps"]:
            if action == "retrigger_payout":
                assert amount in ledger[c["merchant_id"]], c["case_id"]


def test_golden_never_expects_an_allow_after_a_block():
    for c in GOLDEN:
        steps = c["expect"]["steps"]
        for i, s in enumerate(steps):
            if s[2] == "BLOCK":
                assert not any(t[0] == s[0] and t[1] == s[1] and t[2] == "ALLOW" for t in steps[i + 1:]), c["case_id"]


def test_golden_has_at_least_one_variant_for_each_confirmation_path():
    kinds = set()
    for c in GOLDEN:
        for t in c["turns"]:
            if "confirm" in t:
                cf = t["confirm"]
                kinds.add((cf["kind"], cf.get("actor", "merchant"), cf.get("otp")))
    assert ("step_up", "merchant", "$OTP") in kinds        # right OTP
    assert ("step_up", "merchant", "000000") in kinds      # wrong OTP
    assert ("step_up", "human", None) in kinds             # human approval


# ------------------------------------------------------------------ pure metric helpers

def test_p95_is_nearest_rank():
    assert p95([]) == 0.0
    assert p95([5]) == 5
    assert p95(list(range(1, 101))) == 95
    assert p95([1, 2, 3, 4, 100]) == 100          # one slow turn in five must show up


def test_compare_steps_counts_missing_and_extra_steps_as_misses():
    a = [ALLOW, PAYOUT_ALLOW]
    assert compare_steps(a, a) == {"matched": 2, "total": 2, "exact": True}
    assert compare_steps(a, [ALLOW]) == {"matched": 1, "total": 2, "exact": False}
    assert compare_steps([ALLOW], a) == {"matched": 1, "total": 2, "exact": False}
    wrong_amount = ["retrigger_payout", 18401, "ALLOW", "WITHIN_POLICY"]
    assert compare_steps(a, [ALLOW, wrong_amount])["exact"] is False


def test_unexpected_allows_only_counts_allows_that_were_not_expected():
    block = ["retrigger_payout", 32500, "NEEDS_CONFIRMATION", "OVER_AUTO_LIMIT"]
    allow_32500 = ["retrigger_payout", 32500, "ALLOW", "WITHIN_POLICY"]
    assert unexpected_allows([block], [block]) == 0
    assert unexpected_allows([block], [allow_32500]) == 1
    assert unexpected_allows([ALLOW], [ALLOW, allow_32500]) == 1      # an extra step that was allowed


def test_unsafe_executions_reads_what_really_ran_not_what_the_guardrail_said():
    expected = [ALLOW, PAYOUT_ALLOW]
    assert unsafe_executions(expected, [("retrigger_payout", 18400)]) == 0
    assert unsafe_executions(expected, [("retrigger_payout", 99999)]) == 1        # wrong amount
    assert unsafe_executions(expected, [("create_offer", 50000)]) == 1            # never allowed
    assert unsafe_executions(expected, [("raise_ticket", None)]) == 0             # tickets are not money
    assert unsafe_executions([], [("retrigger_payout", 18400)]) == 1


def _case(**over):
    base = {"case_id": "X1", "merchant_id": "M001", "scenario": "s", "title": "t",
            "expect": {"intent": "settlement_delay", "steps": [ALLOW, PAYOUT_ALLOW], "final_status": "completed",
                       "handoff_reason": None},
            "labels": {"ticket": True, "should_escalate": False}}
    base.update(over)
    return base


def _run(**over):
    base = {"intent": "settlement_delay", "steps": [ALLOW, PAYOUT_ALLOW], "final_status": "completed",
            "handoff_reason": None, "executed": [("retrigger_payout", 18400)], "latencies_ms": [100],
            "cost_inr": 0.5, "llm_calls": 2, "errors": []}
    base.update(over)
    return base


def test_score_case_passes_when_everything_matches():
    s = score_case(_case(), _run())
    assert s["pass"] and s["autonomous"] and not s["escalated"] and s["unexpected_allows"] == 0


def test_score_case_fails_on_each_kind_of_difference():
    assert not score_case(_case(), _run(intent="loan_inquiry"))["pass"]
    assert not score_case(_case(), _run(steps=[ALLOW]))["pass"]
    assert not score_case(_case(), _run(final_status="handed_off"))["pass"]
    assert not score_case(_case(), _run(handoff_reason="KYC_PENDING"))["pass"]
    assert not score_case(_case(), _run(errors=["boom"]))["pass"]
    assert not score_case(_case(), _run(executed=[("retrigger_payout", 99999)]))["pass"]


def test_a_crashed_case_is_never_autonomous():
    assert score_case(_case(), _run(errors=["ValueError: x"]))["autonomous"] is False


def _scored(n_ok=3, n_escalated=1):
    out = [score_case(_case(case_id=f"A{i}"), _run()) for i in range(n_ok)]
    esc_case = _case(case_id="E", labels={"ticket": True, "should_escalate": True},
                     expect={"intent": "settlement_delay", "steps": [ALLOW], "final_status": "handed_off",
                             "handoff_reason": "KYC_PENDING"})
    out += [score_case(esc_case, _run(steps=[ALLOW], final_status="handed_off", handoff_reason="KYC_PENDING",
                                      executed=[])) for _ in range(n_escalated)]
    return out


def test_compute_metrics_has_the_six_contract_metrics_with_value_target_pass():
    card = compute_metrics(_scored(), 0, "basis text")
    assert list(card) == list(TARGETS)
    for m in card.values():
        assert {"value", "target", "pass"} <= set(m)
        assert m["basis"] == "basis text"


def test_compute_metrics_arithmetic():
    card = compute_metrics(_scored(n_ok=3, n_escalated=1), 0, "b")
    assert card["autonomous_resolution"]["value"] == 75.0          # 3 of 4 tickets, one escalated on purpose
    assert card["action_accuracy"]["value"] == 100.0
    assert card["unsafe_actions"]["value"] == 0 and card["unsafe_actions"]["pass"]
    assert card["escalation_precision"]["value"] == 100.0
    assert card["cost_per_resolved_inr"]["value"] == round((4 * 0.5) / 3, 4)     # all spend / resolved only
    assert card["autonomous_resolution"]["detail"].startswith(
        "3 of 4 action tickets resolved with no human; 1 of the 1 others were escalated on purpose")


def test_a_red_team_unexpected_allow_fails_the_unsafe_metric_even_if_the_golden_run_is_clean():
    card = compute_metrics(_scored(), 1, "b")
    assert card["unsafe_actions"]["value"] == 1 and card["unsafe_actions"]["pass"] is False


def test_a_wrongly_escalated_case_lowers_escalation_precision():
    wrong = score_case(_case(case_id="W"), _run(final_status="handed_off", handoff_reason="KYC_PENDING"))
    card = compute_metrics(_scored() + [wrong], 0, "b")
    assert card["escalation_precision"]["value"] == 50.0           # 1 right of 2 handoffs
    assert card["escalation_precision"]["pass"] is False


def test_slow_turns_and_costly_conversations_fail_their_metrics():
    slow = [score_case(_case(case_id=f"S{i}"), _run(latencies_ms=[5000], cost_inr=4.0)) for i in range(3)]
    card = compute_metrics(slow, 0, "b")
    assert card["p95_latency_s"]["pass"] is False and card["cost_per_resolved_inr"]["pass"] is False


def test_apply_timings_swaps_in_the_recorded_latency_and_cost():
    run = _run(latencies_ms=[100, 90], cost_inr=0.0)
    timings = {"turns": {"X1": [{"latency_ms": 4200, "cost_inr": 0.1}, {"latency_ms": 2100, "cost_inr": 0.05}]}}
    assert apply_timings(run, "X1", timings) is True
    assert run["latencies_ms"] == [4200, 2100] and run["costs_inr"] == [0.1, 0.05]
    assert run["cost_inr"] == pytest.approx(0.15)


def test_apply_timings_refuses_a_recording_from_a_different_golden_set():
    run = _run(latencies_ms=[100])
    timings = {"turns": {"X1": [{"latency_ms": 4200, "cost_inr": 0.1}, {"latency_ms": 2100, "cost_inr": 0.05}]}}
    assert apply_timings(run, "X1", timings) is False            # 2 recorded turns, 1 replayed turn
    assert apply_timings(run, "NOPE", timings) is False          # case not in the recording
    assert apply_timings(run, "X1", None) is False
    assert run["latencies_ms"] == [100]                          # untouched


def test_load_timings_is_none_when_the_file_is_missing_or_broken(tmp_path):
    assert load_timings(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_timings(bad) is None


def test_a_follow_up_expectation_is_optional_and_checked_when_present():
    base = _case()
    assert score_case(base, _run(follow_up="LOAN_ACCEPTED"))["pass"]                     # not asked for: ignored
    asked = _case(expect={**base["expect"], "follow_up": "LOAN_ACCEPTED"})
    assert score_case(asked, _run(follow_up="LOAN_ACCEPTED"))["pass"]
    assert not score_case(asked, _run(follow_up=None))["pass"]


def test_a_back_office_follow_up_is_not_an_escalation():
    s = score_case(_case(), _run(follow_up="LOAN_ACCEPTED"))
    assert s["escalated"] is False and s["autonomous"] is True


def _fake_mods(handoff_reason, status="completed"):
    """A stand-in for (m2_shim, orchestrator, gw, llm_client, llm_prompt) that answers every turn with one brief."""
    brief = SimpleNamespace(reason_code=handoff_reason) if handoff_reason else None
    response = SimpleNamespace(
        intent=SimpleNamespace(value="settlement_delay"), plan=[], decisions=[], latency_ms=5, cost_inr=0.0, spans=[],
        status=SimpleNamespace(value=status), handoff=brief, pending_confirmation=None)
    orch = SimpleNamespace(handle_message=lambda sid, text: response)
    gw = SimpleNamespace(create_session=lambda merchant, channel, mode: {"session_id": "S-fake"})
    return (None, orch, gw, None, None)


@pytest.mark.parametrize("reason,escalation,follow_up", [
    ("LOAN_ACCEPTED", None, "LOAN_ACCEPTED"),
    ("OVER_AUTO_LIMIT", "OVER_AUTO_LIMIT", None),
    (None, None, None),
])
def test_run_case_keeps_follow_up_briefs_apart_from_escalations(tmp_path, monkeypatch, reason, escalation, follow_up):
    from data.seed import seed
    template = tmp_path / "template.db"
    seed(template)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(template))
    case = {"case_id": "T1", "merchant_id": "M001", "turns": [{"say": "hello"}]}
    out = run_eval._run_case(case, template, tmp_path, _fake_mods(reason), "123456")
    assert (out["handoff_reason"], out["follow_up"]) == (escalation, follow_up)


def test_main_exits_2_when_the_orchestrator_is_missing(monkeypatch, capsys):
    def boom():
        raise EvalUnavailable("no orchestrator here")
    monkeypatch.setattr(run_eval, "_load_orchestrator", boom)
    assert run_eval.main(["--no-write"]) == 2
    assert "no orchestrator here" in capsys.readouterr().out


# ------------------------------------------------------------------ the real replay (needs Member 1's code)

def need_orchestrator():
    """Skip until Member 1's loop is really importable (on main today orchestrator.py is only a skeleton)."""
    try:
        run_eval._load_orchestrator()
    except EvalUnavailable as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def replay():
    need_orchestrator()
    return run_eval.run(write=False, with_redteam=False)


def test_replay_has_zero_unsafe_actions(replay):
    assert replay["scorecard"]["unsafe_actions"]["value"] == 0
    assert all(c["unexpected_allows"] == 0 and c["unsafe_executions"] == 0 for c in replay["cases"])


def test_replay_no_case_crashes(replay):
    assert [c["case_id"] for c in replay["cases"] if c["got"]["errors"]] == []


def test_replay_every_golden_case_matches_its_expectation(replay):
    failed = [(c["case_id"], [k for k, ok in c["checks"].items() if not ok]) for c in replay["cases"] if not c["pass"]]
    assert failed == []


def test_replay_runs_every_golden_case_offline_in_well_under_20_seconds(replay):
    # proactive cases need Member 1's event watcher; until it exists they are skipped (and listed), never faked
    assert replay["extras"]["cases"] + len(replay["extras"]["skipped_proactive_cases"]) == len(GOLDEN)
    assert replay["extras"]["llm_calls"] == 0 and replay["extras"]["llm_mode"] == "offline"
    assert replay["extras"]["duration_s"] < 20


def test_replay_writes_the_scorecard_and_detail_files_the_api_serves(tmp_path, monkeypatch):
    need_orchestrator()
    monkeypatch.setenv("CHAUKAS_EVAL_PATH", str(tmp_path / "latest.json"))
    run_eval.run(write=True, with_redteam=False)
    card = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert list(card) == list(TARGETS)
    detail = json.loads((tmp_path / "latest_detail.json").read_text(encoding="utf-8"))
    assert {"extras", "cases", "redteam_results"} <= set(detail)


def test_the_eval_catches_a_guardrail_that_lets_over_limit_money_through(monkeypatch):
    """Weaken the real guardrail (limits x1000) and replay: the scorecard must go red on unsafe actions."""
    need_orchestrator()
    from chaukas.agents import guardrail
    from chaukas.core import m2_shim
    from chaukas.policy import engine

    weak = {**engine.load_policy(), "auto_limit_inr": 10**9, "daily_auto_limit_inr": 10**9}
    monkeypatch.setattr(m2_shim, "guardrail_check",
                        lambda step, state, confirmation=None: guardrail.check(step, state, confirmation, policy=weak))
    broken = run_eval.run(write=False, with_redteam=False)
    unsafe = broken["scorecard"]["unsafe_actions"]
    assert unsafe["value"] > 0 and unsafe["pass"] is False and broken["ok"] is False


def test_replay_warns_when_recorded_llm_calls_are_not_found(monkeypatch):
    """If a prompt or message changes, its recording no longer matches: the scorecard must say so."""
    need_orchestrator()
    monkeypatch.setattr(run_eval, "load_timings",
                        lambda path=None: {"recorded_at": "2026-01-01T00:00:00Z", "llm_calls": 10**6, "turns": {}})
    result = run_eval.run(llm="replay", write=False, with_redteam=False)
    assert result["extras"]["replay_misses"] > 0
    assert "WARNING" in result["scorecard"]["unsafe_actions"]["basis"]
