"""Run data/redteam_set.json. Any unexpected ALLOW = failure.

Owner: Member 2 · Contract: design B8 / CONTRACTS C2

Every case gets its own freshly seeded copy of the DB, so cases cannot affect each other.
Each step goes straight to guardrail.check() (no LLM, no tools, nothing is executed except the
pending/success bookkeeping row that `then_execute` writes to mimic the Action agent).

    python -m eval.redteam            exit code 0 = clean, 1 = something failed
"""
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from chaukas.agents import guardrail
from chaukas.api.ops import make_redteam_state
from chaukas.compliance import consent
from chaukas.core.models import Confirmation, LenderDecision, PlannedStep
from chaukas.db import ROOT, connect
from chaukas.observability import audit
from chaukas.policy import engine
from data.seed import seed

REDTEAM_PATH = ROOT / "data" / "redteam_set.json"
FIXTURES_PATH = ROOT / "data" / "merchant_fixtures.json"
RESULT_PATH = ROOT / "eval" / "redteam_latest.json"
EVAL_OTP = "123456"   # used only when config/mock.yaml has no otp yet


def _fixture_eligibility() -> dict[str, LenderDecision]:
    """The simulated lender's expected answer per merchant (the test oracle in merchant_fixtures.json)."""
    data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["merchants"]
    return {m["merchant_id"]: LenderDecision(**m["expected_loan_eligibility"]) for m in data}


def _apply_setup(conn, merchant_id: str, ops: list[dict]) -> None:
    for op in ops:
        if op["op"] == "set_kyc":
            conn.execute("UPDATE merchants SET kyc_status = ? WHERE merchant_id = ?", (op["status"], merchant_id))
        elif op["op"] == "settlement_status":
            conn.execute("UPDATE settlements SET status = ? WHERE id = ?", (op["status"], op["id"]))
        elif op["op"] == "withdraw_consent":
            consent.withdraw(conn, merchant_id, op["purpose"])
        elif op["op"] == "insurance_lead":        # an earlier lead: interested (already asked) or declined (cooling-off)
            declined = op["status"] == "declined"
            conn.execute(
                "INSERT INTO insurance_leads (id, merchant_id, product_id, product_name, insurer_name, cover_inr, "
                "premium_inr, consent_at, declined_at, status) VALUES ('INS-RT', ?, ?, 'x', 'x', 1000, 10, ?, ?, ?)",
                (merchant_id, op["product_id"], None if declined else "2026-10-31T00:00:00Z",
                 "2099-01-01T00:00:00Z" if declined else None, op["status"]))
        elif op["op"] == "open_handoff":
            conn.execute("INSERT INTO sessions (session_id, merchant_id) VALUES ('rt-setup', ?)", (merchant_id,))
            conn.execute("INSERT INTO handoffs (id, session_id, merchant_id, trace_id, reason_code, brief_json, "
                         "decision_needed) VALUES ('HO-RT', 'rt-setup', ?, 't', 'LOW_CONFIDENCE', '{}', 'x')",
                         (merchant_id,))
        else:
            raise ValueError(f"unknown setup op: {op['op']}")
    conn.commit()


def _run_case(case: dict, template_db: Path, workdir: Path, otp: str, oracle: dict, policy_patch: dict | None) -> dict:
    db_file = workdir / f"{case['case_id']}.db"
    shutil.copy(template_db, db_file)
    conn = connect(db_file)
    steps_out = []
    try:
        merchant_id = case["merchant_id"]
        _apply_setup(conn, merchant_id, case.get("setup", []))

        policy = engine.load_policy()
        policy.update(case.get("policy_override", {}))
        policy.update(policy_patch or {})

        elig = case.get("eligibility")
        lender = oracle[merchant_id] if elig == "fixture" else (LenderDecision(**elig) if elig else None)
        state = make_redteam_state(conn, merchant_id, lender, run_id=case["case_id"],
                                   trigger_source=case.get("trigger_source", "merchant"))
        if "spoof_state_trigger" in case:   # attacker/bug lies in the in-memory state; the DB row must win
            state.__dict__["trigger_source"] = case["spoof_state_trigger"]

        audit_ids: list[int | None] = []
        for i, raw in enumerate(case["steps"]):
            step_no = raw.get("step_no", i + 1)
            if "pre" in raw:    # DB change between steps, e.g. the payout went through (settlement -> retriggered)
                _apply_setup(conn, merchant_id, raw["pre"])
            step = PlannedStep(step_no=step_no, action_type=raw["action_type"], params=raw["params"],
                               amount=raw.get("amount"), rationale="red-team")
            confirmation = None
            if "confirm" in raw:
                c = raw["confirm"]
                confirmation = Confirmation(
                    pending_audit_id=audit_ids[c["pending_from"]], actor=c["actor"], actor_id=c.get("actor_id"),
                    kind=c["kind"], otp=otp if c.get("otp") == "$OTP" else c.get("otp"))
            d = guardrail.check(step, state, confirmation, conn=conn, policy=policy, actor="system")
            audit_ids.append(d.audit_id)

            if raw.get("then_execute") and d.verdict.value == "ALLOW":
                audit.start_execution(conn, idempotency_key=f"{state.session_id}:{step_no}", audit_id=d.audit_id,
                                      trace_id=state.trace_id, session_id=state.session_id, merchant_id=merchant_id,
                                      action_type=step.action_type, amount=step.amount)
                audit.finish_execution(conn, f"{state.session_id}:{step_no}", "success", result_ref="REDTEAM")

            expect = raw["expect"]
            got = {"verdict": d.verdict.value, "reason_code": d.reason_code.value}
            steps_out.append({
                "step": i + 1, "action_type": raw["action_type"], "amount": raw.get("amount"),
                "expect": expect, "got": got, "reason": d.reason,
                "pass": got == expect,
                "unsafe": got["verdict"] == "ALLOW" and expect["verdict"] != "ALLOW",
            })
    finally:
        conn.close()
    return {"case_id": case["case_id"], "attack": case["attack"], "title": case["title"],
            "merchant_id": case["merchant_id"], "steps": steps_out,
            "pass": all(s["pass"] for s in steps_out), "unsafe": any(s["unsafe"] for s in steps_out)}


def run(path: Path | None = None, *, write: bool = True, policy_patch: dict | None = None) -> dict:
    """Run every case and return the summary. `policy_patch` weakens the policy on purpose (used by the
    test that proves this runner really catches a broken guardrail)."""
    started = time.perf_counter()
    cases = json.loads(Path(path or REDTEAM_PATH).read_text(encoding="utf-8"))["cases"]
    oracle = _fixture_eligibility()

    configured_otp = engine.load_mock_otp()
    original_loader = engine.load_mock_otp
    if not configured_otp:
        engine.load_mock_otp = lambda: EVAL_OTP        # pinned for this run only
    try:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            template = workdir / "template.db"
            seed(template)
            results = [_run_case(c, template, workdir, configured_otp or EVAL_OTP, oracle, policy_patch)
                       for c in cases]
    finally:
        engine.load_mock_otp = original_loader

    steps = [s for r in results for s in r["steps"]]
    summary = {
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cases": len(results), "steps": len(steps),
        "passed_cases": sum(r["pass"] for r in results),
        "failed_cases": sum(not r["pass"] for r in results),
        "unexpected_allows": sum(s["unsafe"] for s in steps),
        "mock_otp_pinned": not configured_otp,
        "duration_s": round(time.perf_counter() - started, 2),
        "ok": all(r["pass"] for r in results) and not any(r["unsafe"] for r in results),
        "results": results,
    }
    if write:
        RESULT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _print(summary: dict) -> None:
    print(f"{'case':<6} {'attack':<18} {'merchant':<9} {'expected':<46} {'got':<46} result")
    for r in summary["results"]:
        for s in r["steps"]:
            exp = f"{s['expect']['verdict']} {s['expect']['reason_code']}"
            got = f"{s['got']['verdict']} {s['got']['reason_code']}"
            flag = "UNSAFE" if s["unsafe"] else ("PASS" if s["pass"] else "FAIL")
            print(f"{r['case_id']:<6} {r['attack']:<18} {r['merchant_id']:<9} {exp:<46} {got:<46} {flag}")
    print()
    print(f"{summary['cases']} cases / {summary['steps']} steps: {summary['passed_cases']} passed, "
          f"{summary['failed_cases']} failed, UNEXPECTED ALLOWS = {summary['unexpected_allows']} "
          f"({summary['duration_s']}s)")
    if summary["mock_otp_pinned"]:
        print("note: config/mock.yaml has no 'otp'; the eval pinned a mock OTP for this run")
    print("RESULT:", "OK - 0 unsafe actions" if summary["ok"] else "FAILED")


if __name__ == "__main__":
    result = run()
    _print(result)
    sys.exit(0 if result["ok"] else 1)
