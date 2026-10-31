"""Retention window and erasure (DPDP s.8, s.11-12): what is purged, what is kept, and that audit stays intact.

Owner: Member 2 · COMPLIANCE.md D6, D7
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chaukas.agents import guardrail
from chaukas.api import ops
from chaukas.compliance import consent, retention
from chaukas.db import connect
from chaukas.policy import engine
from data.seed import seed

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
FIXTURES = json.loads((retention.query_one.__globals__["ROOT"] / "data" / "merchant_fixtures.json")
                      .read_text(encoding="utf-8"))["merchants"]


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_session(conn, session_id, merchant_id):
    conn.execute("INSERT INTO sessions (session_id, merchant_id) VALUES (?, ?)", (session_id, merchant_id))


def add_turn(conn, session_id, turn_no, text, days_ago, trace_id=None):
    conn.execute("INSERT INTO turns (session_id, turn_no, trace_id, role, text_masked, lang, intent, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)",
                 (session_id, turn_no, trace_id or f"T-{session_id}-{turn_no}", "merchant", text, "hi-IN",
                  "settlement_delay", iso(days_ago)))
    conn.commit()


def texts(conn, session_id):
    return [r["text_masked"] for r in conn.execute(
        "SELECT text_masked FROM turns WHERE session_id = ? ORDER BY turn_no", (session_id,))]


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ------------------------------------------------------------------ the window comes from policy, not code

def test_the_window_is_read_from_policy():
    assert retention.retention_days() == engine.load_policy()["retention_days"] == 90


@pytest.mark.parametrize("bad", [0, -5, "90", None, True])
def test_a_broken_retention_setting_is_refused(bad):
    with pytest.raises(ValueError):
        retention.retention_days({"retention_days": bad})


# ------------------------------------------------------------------ D6: purge

def test_old_turns_are_anonymised_and_recent_ones_are_kept(db):
    add_session(db, "S1", "M001")
    add_turn(db, "S1", 1, "mera XXXXXX0001 settlement", days_ago=120)
    add_turn(db, "S1", 2, "kal ki baat", days_ago=91)
    add_turn(db, "S1", 3, "pichle hafte ki baat", days_ago=89)
    add_turn(db, "S1", 4, "aaj ki baat", days_ago=0)
    changed = retention.purge_turns(db, now=NOW)
    assert changed == 2
    assert texts(db, "S1") == [retention.RETENTION_MARK, retention.RETENTION_MARK, "pichle hafte ki baat", "aaj ki baat"]


def test_the_boundary_is_strictly_older_than_the_window(db):
    add_session(db, "S1", "M001")
    add_turn(db, "S1", 1, "exactly on the line", days_ago=90)
    add_turn(db, "S1", 2, "one second older", days_ago=90 + 1 / 86400)
    retention.purge_turns(db, now=NOW)
    assert texts(db, "S1") == ["exactly on the line", retention.RETENTION_MARK]


def test_purge_keeps_the_row_and_its_analytics_fields(db):
    add_session(db, "S1", "M001")
    add_turn(db, "S1", 1, "old", days_ago=200)
    retention.purge_turns(db, now=NOW)
    row = db.execute("SELECT * FROM turns").fetchone()
    assert (row["turn_no"], row["lang"], row["intent"], row["role"]) == (1, "hi-IN", "settlement_delay", "merchant")


def test_purge_is_idempotent_and_does_not_touch_erased_turns(db):
    add_session(db, "S1", "M001")
    add_turn(db, "S1", 1, retention.ERASED_MARK, days_ago=300)
    add_turn(db, "S1", 2, "old", days_ago=300)
    assert retention.purge_turns(db, now=NOW) == 1
    assert retention.purge_turns(db, now=NOW) == 0
    assert texts(db, "S1") == [retention.ERASED_MARK, retention.RETENTION_MARK]


def test_purge_never_touches_the_append_only_tables(db):
    add_session(db, "S1", "M001")
    add_turn(db, "S1", 1, "old", days_ago=300)
    consent.grant(db, "M001", "ai_assistance")
    db.execute("INSERT INTO audit_log (trace_id, session_id, merchant_id, actor, step_no, action_type, "
               "params_masked, guardrail_decision, reason_code, reason) VALUES "
               "('t','S1','M001','agent',1,'verify_ledger','{}','ALLOW','WITHIN_POLICY','ok')")
    db.commit()
    before = (count(db, "audit_log"), count(db, "consents"))
    retention.purge(db, now=NOW + timedelta(days=1000), trace_dir=None)
    assert (count(db, "audit_log"), count(db, "consents")) == before


def test_old_trace_files_are_deleted_and_recent_ones_kept(tmp_path):
    old, new = tmp_path / "T-old.jsonl", tmp_path / "T-new.jsonl"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    os.utime(old, ((NOW - timedelta(days=120)).timestamp(),) * 2)
    os.utime(new, ((NOW - timedelta(days=5)).timestamp(),) * 2)
    (tmp_path / "keep.txt").write_text("not a trace", encoding="utf-8")
    assert retention.purge_traces(trace_dir=tmp_path, now=NOW) == 1
    assert not old.exists() and new.exists() and (tmp_path / "keep.txt").exists()


def test_purge_traces_with_no_folder_is_a_no_op(tmp_path):
    assert retention.purge_traces(trace_dir=tmp_path / "nope", now=NOW) == 0


# ------------------------------------------------------------------ D7: access summary

def test_data_summary_shows_only_masked_personal_fields(db):
    add_session(db, "S1", "M001")
    add_turn(db, "S1", 1, "hello", days_ago=1)
    s = retention.data_summary(db, "M001")
    m1 = next(m for m in FIXTURES if m["merchant_id"] == "M001")
    blob = json.dumps(s, ensure_ascii=False)
    for value in (m1["name"], *m1["pii"].values()):
        assert value not in blob
    assert s["profile"]["phone"] == "XXXXXX0001" and s["profile"]["name"].endswith("****")
    assert s["counts"]["sessions"] == 1 and s["counts"]["turns"] == 1
    assert s["retention_days"] == 90 and set(s["kept_after_erasure"]) == set(retention.RETAINED)


def test_data_summary_for_an_unknown_merchant(db):
    with pytest.raises(retention.MerchantNotFound):
        retention.data_summary(db, "M999")


# ------------------------------------------------------------------ D7: erasure

def pii_values(merchant_id):
    m = next(m for m in FIXTURES if m["merchant_id"] == merchant_id)
    return [m["name"], *m["pii"].values()]


def test_erasure_blanks_the_personal_fields_of_that_merchant_only(db):
    retention.erase_merchant(db, "M001", now=NOW)
    row = db.execute("SELECT * FROM merchants WHERE merchant_id = 'M001'").fetchone()
    assert row["name"] == retention.ERASED_NAME
    assert all(row[c] is None for c in retention.PII_COLUMNS)
    other = db.execute("SELECT * FROM merchants WHERE merchant_id = 'M002'").fetchone()
    assert other["name"] == next(m["name"] for m in FIXTURES if m["merchant_id"] == "M002")
    assert other["phone"] and other["account_no"]
    # the row itself stays: other tables point at it
    assert db.execute("SELECT COUNT(*) FROM settlements WHERE merchant_id = 'M001'").fetchone()[0] > 0


def test_erasure_leaves_no_trace_of_the_raw_values_in_any_table(db):
    retention.erase_merchant(db, "M001", now=NOW)
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    dump = json.dumps({t: [dict(r) for r in db.execute(f"SELECT * FROM {t}")] for t in tables}, default=str)
    for value in pii_values("M001"):
        assert value not in dump


def test_erasure_anonymises_only_that_merchants_turns_and_handoffs(db):
    add_session(db, "S1", "M001")
    add_session(db, "S2", "M002")
    add_turn(db, "S1", 1, "XXXXXX0001 ka settlement", days_ago=1)
    add_turn(db, "S2", 1, "dusre merchant ki baat", days_ago=1)
    brief = {"asked": "XXXXXX0001 ka settlement", "verified": ["ledger"], "done": [], "refused": [],
             "reason_code": "OVER_AUTO_LIMIT", "confidence": 0.9, "decision_needed": "approve"}
    db.execute("INSERT INTO handoffs (id, session_id, merchant_id, trace_id, reason_code, brief_json, decision_needed) "
               "VALUES ('HO-1','S1','M001','t','OVER_AUTO_LIMIT',?, 'approve')", (json.dumps(brief),))
    db.commit()
    receipt = retention.erase_merchant(db, "M001", now=NOW)
    assert texts(db, "S1") == [retention.ERASED_MARK]
    assert texts(db, "S2") == ["dusre merchant ki baat"]
    stored = json.loads(db.execute("SELECT brief_json FROM handoffs WHERE id = 'HO-1'").fetchone()[0])
    assert stored["asked"] == retention.ERASED_MARK and stored["reason_code"] == "OVER_AUTO_LIMIT"
    assert receipt["anonymised"]["turns"] == 1 and receipt["anonymised"]["handoffs"] == 1


def test_erasure_keeps_the_loan_follow_up_details_of_a_brief(db):
    """A LOAN_ACCEPTED brief carries lender, APR, fee, tenure and the consent audit id: all kept, none of it personal."""
    add_session(db, "S1", "M001")
    loan = {"offer_id": "OFF-1", "amount": 50000, "lender_name": "Demo NBFC Partner (simulated)", "apr_pct": 18.0,
            "processing_fee_inr": 500, "tenure_months": 12, "total_repayable_inr": 59500,
            "grievance_contact": "grievance@demo-lender.example (mock)", "kfs_shown_at": "2026-10-31T09:00:00Z",
            "consent_at": "2026-10-31T09:01:00Z", "consent_audit_id": 7}
    brief = {"asked": "Merchant accepted a loan offer", "verified": [], "done": [], "refused": [],
             "reason_code": "LOAN_ACCEPTED", "confidence": 1.0, "decision_needed": "follow up", "loan": loan}
    db.execute("INSERT INTO handoffs (id, session_id, merchant_id, trace_id, reason_code, brief_json, decision_needed) "
               "VALUES ('HO-L','S1','M001','t','LOAN_ACCEPTED',?, 'follow up')", (json.dumps(brief),))
    db.commit()
    retention.erase_merchant(db, "M001", now=NOW)
    stored = json.loads(db.execute("SELECT brief_json FROM handoffs WHERE id = 'HO-L'").fetchone()[0])
    assert stored["loan"] == loan and stored["reason_code"] == "LOAN_ACCEPTED"
    assert stored["asked"] == retention.ERASED_MARK


def test_erasure_keeps_every_record_the_law_requires(db):
    consent.grant(db, "M001", "ai_assistance")
    before = {t: count(db, t) for t in ("audit_log", "executions", "offers", "tickets", "ticket_events",
                                        "settlements", "cashflow_features")}
    receipt = retention.erase_merchant(db, "M001", now=NOW)
    assert {t: count(db, t) for t in before} == before
    assert set(receipt["kept"]) >= set(before) | {"consents"}
    assert count(db, "consents") >= 3         # the history only grew: grant, then two withdrawals


def test_erasure_withdraws_both_consents_so_no_offer_is_made_again(db, make_state, make_step):
    consent.grant(db, "M001", "ai_assistance")
    receipt = retention.erase_merchant(db, "M001", now=NOW)
    assert set(receipt["consents_withdrawn_now"]) == {"ai_assistance", "loan_offer"}
    assert consent.is_withdrawn(db, "M001", "ai_assistance") and consent.is_withdrawn(db, "M001", "loan_offer")
    d = guardrail.check(make_step("create_offer", {"merchant_id": "M001", "amount": 50000}, amount=50000),
                        make_state("M001", eligible=(True, 50000)), None, conn=db, policy=engine.load_policy())
    assert (d.verdict.value, d.reason_code.value) == ("BLOCK", "CONSENT_WITHDRAWN")


def test_erasure_is_idempotent(db):
    first = retention.erase_merchant(db, "M001", now=NOW)
    n = count(db, "consents")
    second = retention.erase_merchant(db, "M001", now=NOW)
    assert count(db, "consents") == n                       # no duplicate withdrawal rows
    assert second["consents_withdrawn_now"] == []
    assert first["consents_withdrawn_now"] != []


def test_erasure_deletes_that_merchants_trace_files_only(db, tmp_path):
    add_session(db, "S1", "M001")
    add_session(db, "S2", "M002")
    add_turn(db, "S1", 1, "x", days_ago=1, trace_id="T-mine")
    add_turn(db, "S2", 1, "y", days_ago=1, trace_id="T-theirs")
    for name in ("T-mine", "T-theirs"):
        (tmp_path / f"{name}.jsonl").write_text("{}", encoding="utf-8")
    receipt = retention.erase_merchant(db, "M001", now=NOW, trace_dir=tmp_path)
    assert not (tmp_path / "T-mine.jsonl").exists() and (tmp_path / "T-theirs.jsonl").exists()
    assert receipt["anonymised"]["trace_files_deleted"] == 1


def test_erasing_an_unknown_merchant_changes_nothing(db):
    with pytest.raises(retention.MerchantNotFound):
        retention.erase_merchant(db, "M999")
    assert count(db, "consents") == 0


# ------------------------------------------------------------------ the API

@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "rights.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    monkeypatch.setenv("CHAUKAS_TRACE_DIR", str(tmp_path / "traces"))
    app = FastAPI()
    app.include_router(ops.router)
    return TestClient(app)


def test_api_data_summary_then_erasure_then_summary_again(client):
    s = client.get("/api/merchants/M001/data-summary").json()
    assert s["profile"]["phone"] == "XXXXXX0001"
    r = client.post("/api/merchants/M001/erasure")
    assert r.status_code == 200
    receipt = r.json()
    assert receipt["merchant_id"] == "M001" and receipt["anonymised"]["merchants"] == 1
    after = client.get("/api/merchants/M001/data-summary").json()
    assert after["profile"]["phone"] is None and after["profile"]["name"] == "Er****"
    assert after["consents"]["loan_offer"]["state"] == "withdrawn"
    assert "M001" not in json.dumps(client.get("/api/merchants/M002/data-summary").json()["profile"])


@pytest.mark.parametrize("method,url", [("get", "/api/merchants/M999/data-summary"), ("post", "/api/merchants/M999/erasure")])
def test_api_unknown_merchant_is_a_404_in_the_contract_shape(client, method, url):
    r = getattr(client, method)(url)
    assert r.status_code == 404 and r.json()["error"]["code"] == "MERCHANT_NOT_FOUND"
