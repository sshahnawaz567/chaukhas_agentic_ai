"""Shop insurance: which product fits a merchant, the guardrail around the offer, and the whole conversation.

Owner: Member 2 (rules, guardrail, eval) with Member 1's plan / orchestrator / reply hooks · COMPLIANCE.md I1-I4

What the feature promises, and what these tests pin:
  - the recommendation is deterministic rules over fresh DB facts (category, sales, device, PAST support tickets): no LLM
  - the guardrail asks for the merchant's own yes, and the product must be the one the rules recommend right now
  - a yes records INTEREST only: no premium is charged, no policy is issued, no payout moves
  - support comes first: an open issue, pending KYC, an open handoff or a recent "no" all block the pitch
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from chaukas.agents import guardrail
from chaukas.compliance import consent
from chaukas.core.models import Confirmation
from chaukas.db import ROOT, connect
from chaukas.integrations import insurance
from chaukas.integrations._common import load_config
from chaukas.policy import engine
from data.seed import seed

FIXTURES = json.loads((ROOT / "data" / "merchant_fixtures.json").read_text(encoding="utf-8"))["merchants"]

# What the rules must say for every fixture merchant (written by hand from the fixtures and config/insurance_sim.yaml)
EXPECTED = {
    "M001": "SHOP_FIRE", "M002": "ELECTRONICS_PARTS", "M003": None, "M004": "ELECTRONICS_PARTS", "M005": "SHOP_FIRE",
    "M006": "SHOP_FIRE", "M007": "SHOP_FIRE", "M008": "SHOP_FIRE", "M009": "SHOP_FIRE", "M010": "SHOP_FIRE",
    "M011": "SHOP_FIRE", "M012": "SHOP_FIRE", "M013": "SHOP_FIRE", "M014": "SHOP_FIRE", "M015": "SHOP_FIRE",
    "M016": "SHOP_FIRE", "M017": "DEVICE_PROTECT", "M018": "SHOP_FIRE", "M019": "SHOP_FIRE", "M020": None,
}


def product_of(conn, merchant_id):
    r = insurance.recommend(conn, merchant_id)
    return r["product_id"] if r else None


# ------------------------------------------------------------------ the rules

@pytest.mark.parametrize("merchant_id,product", sorted(EXPECTED.items()))
def test_every_fixture_merchant_gets_the_product_the_rules_say(db, merchant_id, product):
    assert product_of(db, merchant_id) == product


def test_electronics_shops_get_electronics_parts_cover_first_and_shop_fire_as_the_alternative(db):
    for mid in ("M002", "M004"):
        r = insurance.recommend(db, mid)
        assert r["product_id"] == "ELECTRONICS_PARTS" and r["alternatives"] == ["SHOP_FIRE"]
        assert "CATEGORY_ELECTRONICS" in r["reasons"]


def test_device_protection_needs_a_past_device_ticket_the_past_case(db):
    assert product_of(db, "M017") == "DEVICE_PROTECT"
    assert "DEVICE_TICKET_HISTORY" in insurance.recommend(db, "M017")["reasons"]
    db.execute("DELETE FROM tickets WHERE merchant_id = 'M017'")           # no past case any more
    db.commit()
    assert product_of(db, "M017") is None                                   # (and 48,000 is below the shop-fire floor)


def test_a_device_ticket_is_found_by_its_words_not_by_its_id(db):
    assert product_of(db, "M008") == "SHOP_FIRE"                            # no device ticket: shop fire only
    db.execute("INSERT INTO tickets (id, merchant_id, issue, status) VALUES ('TKT-1','M008','soundbox not working','open')")
    db.commit()
    assert product_of(db, "M008") == "DEVICE_PROTECT"                       # device ticket + device: more specific


def test_small_shops_and_unknown_categories_get_nothing(db):
    assert product_of(db, "M003") is None and product_of(db, "M020") is None          # sales below the 50,000 floor
    db.execute("UPDATE merchants SET business_category = NULL WHERE merchant_id = 'M001'")
    db.commit()
    assert product_of(db, "M001") is None
    assert insurance.recommend(db, "M999") is None


def test_the_answer_follows_the_database_it_is_never_cached(db):
    assert product_of(db, "M001") == "SHOP_FIRE"
    before = insurance.recommend(db, "M001")["cover_inr"]
    db.execute("UPDATE merchants SET business_category = 'electronics', gmv_30d = 400000 WHERE merchant_id = 'M001'")
    db.commit()
    now = insurance.recommend(db, "M001")
    assert now["product_id"] == "ELECTRONICS_PARTS" and now["cover_inr"] != before


def test_cover_and_premium_are_int_rupees_that_follow_the_config(db):
    cfg = load_config("insurance_sim")
    for mid in EXPECTED:
        r = insurance.recommend(db, mid)
        if r is None:
            continue
        assert type(r["cover_inr"]) is int and type(r["premium_inr"]) is int and r["cover_inr"] > 0 and r["premium_inr"] > 0
        p = cfg["products"][r["product_id"]]
        if "cover_inr" in p:
            assert (r["cover_inr"], r["premium_inr"]) == (p["cover_inr"], p["premium_inr"])
        else:
            assert r["cover_inr"] % p["round_to"] == 0 and r["cover_inr"] <= p["max_cover_inr"]
            assert r["premium_inr"] == round(r["cover_inr"] * p["premium_rate_pct"] / 100)
        assert r["insurer_name"] == cfg["insurer_name"] and r["reasons"] and r["covers"]


def test_the_recommendation_is_deterministic(db):
    assert insurance.recommend(db, "M004") == insurance.recommend(db, "M004")


def test_the_ids_in_the_priority_list_all_exist():
    cfg = load_config("insurance_sim")
    assert set(cfg["priority"]) == set(cfg["products"])


# ------------------------------------------------------------------ the guardrail

def offer(make_step, mid, product, **extra):
    return make_step("offer_insurance", {"merchant_id": mid, "product_id": product, **extra})


def check(db, policy, make_state, step, mid, confirmation=None, now=None, session="S1"):
    d = guardrail.check(step, make_state(mid, session_id=session), confirmation, conn=db, policy=policy, now=now)
    return d.verdict.value, d.reason_code.value, d


def test_check_insurance_is_read_only_and_never_written_to_the_audit_log(db, policy, make_state, make_step):
    verdict, code, d = check(db, policy, make_state, make_step("check_insurance", {"merchant_id": "M004"}), "M004")
    assert (verdict, code) == ("ALLOW", "WITHIN_POLICY")
    assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_the_offer_waits_for_the_merchants_own_yes_and_then_runs(db, policy, make_state, make_step):
    step = offer(make_step, "M004", "ELECTRONICS_PARTS")
    verdict, code, d = check(db, policy, make_state, step, "M004")
    assert (verdict, code) == ("NEEDS_CONFIRMATION", "CONSENT_REQUIRED") and d.confirmation_kind == "consent"
    yes = Confirmation(pending_audit_id=d.audit_id, actor="merchant", kind="consent")
    assert check(db, policy, make_state, step, "M004", yes)[:2] == ("ALLOW", "CONFIRMED_BY_MERCHANT")


def test_a_yes_is_single_use(db, policy, make_state, make_step):
    step = offer(make_step, "M004", "ELECTRONICS_PARTS")
    d = check(db, policy, make_state, step, "M004")[2]
    yes = Confirmation(pending_audit_id=d.audit_id, actor="merchant", kind="consent")
    assert check(db, policy, make_state, step, "M004", yes)[0] == "ALLOW"
    assert check(db, policy, make_state, step, "M004", yes)[0] == "NEEDS_CONFIRMATION"


def test_a_yes_for_one_product_cannot_be_spent_on_another(db, policy, make_state, make_step):
    d = check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS"), "M004")[2]
    yes = Confirmation(pending_audit_id=d.audit_id, actor="merchant", kind="consent")
    other = offer(make_step, "M004", "SHOP_FIRE")
    assert check(db, policy, make_state, other, "M004", yes)[:2] == ("BLOCK", "OFFER_NOT_ELIGIBLE")


@pytest.mark.parametrize("mid,product", [("M001", "ELECTRONICS_PARTS"), ("M004", "NOT_A_PRODUCT"), ("M003", "SHOP_FIRE"),
                                        ("M017", "SHOP_FIRE")])
def test_only_the_recommended_product_can_be_offered(db, policy, make_state, make_step, mid, product):
    assert check(db, policy, make_state, offer(make_step, mid, product), mid)[:2] == ("BLOCK", "OFFER_NOT_ELIGIBLE")


def test_params_are_strict_no_amount_no_extra_keys_no_other_merchant(db, policy, make_state, make_step):
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS", amount=5), "M004")[:2] == ("BLOCK", "INVALID_PARAMS")
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS", premium_inr=1), "M004")[:2] == ("BLOCK", "INVALID_PARAMS")
    assert check(db, policy, make_state, make_step("offer_insurance", {"merchant_id": "M004"}), "M004")[:2] == ("BLOCK", "INVALID_PARAMS")
    assert check(db, policy, make_state, offer(make_step, "M002", "ELECTRONICS_PARTS"), "M004")[:2] == ("BLOCK", "INVALID_PARAMS")


def test_an_open_issue_pending_kyc_or_open_handoff_each_block_the_pitch(db, policy, make_state, make_step):
    # M004 is clean
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS"), "M004")[0] == "NEEDS_CONFIRMATION"
    db.execute("UPDATE merchants SET kyc_status = 'pending' WHERE merchant_id = 'M004'")
    db.commit()
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS"), "M004")[:2] == ("BLOCK", "ISSUE_UNRESOLVED")
    db.execute("UPDATE merchants SET kyc_status = 'verified' WHERE merchant_id = 'M004'")
    db.execute("INSERT INTO sessions (session_id, merchant_id) VALUES ('s-h','M004')")
    db.execute("INSERT INTO handoffs (id, session_id, merchant_id, trace_id, reason_code, brief_json, decision_needed) "
               "VALUES ('HO-1','s-h','M004','t','LOW_CONFIDENCE','{}','x')")
    db.commit()
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS"), "M004")[:2] == ("BLOCK", "ISSUE_UNRESOLVED")
    # M002 has a failed settlement: support comes first
    assert check(db, policy, make_state, offer(make_step, "M002", "ELECTRONICS_PARTS"), "M002")[:2] == ("BLOCK", "ISSUE_UNRESOLVED")


def test_withdrawn_insurance_consent_blocks_and_a_yes_cannot_lift_it(db, policy, make_state, make_step):
    consent.withdraw(db, "M004", "insurance_offer")
    step = offer(make_step, "M004", "ELECTRONICS_PARTS")
    verdict, code, d = check(db, policy, make_state, step, "M004")
    assert (verdict, code) == ("BLOCK", "CONSENT_WITHDRAWN")
    yes = Confirmation(pending_audit_id=d.audit_id, actor="merchant", kind="consent")
    assert check(db, policy, make_state, step, "M004", yes)[:2] == ("BLOCK", "CONSENT_WITHDRAWN")
    consent.grant(db, "M004", "insurance_offer")                                   # giving it again lifts the block
    assert check(db, policy, make_state, step, "M004")[0] == "NEEDS_CONFIRMATION"


def test_withdrawing_loan_consent_does_not_block_insurance_and_the_other_way_round(db, policy, make_state, make_step):
    consent.withdraw(db, "M004", "loan_offer")
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS"), "M004")[0] == "NEEDS_CONFIRMATION"


def test_an_interested_lead_blocks_a_second_one_and_a_recent_no_starts_the_cooling_off(db, policy, make_state, make_step):
    step = offer(make_step, "M004", "ELECTRONICS_PARTS")
    db.execute("INSERT INTO insurance_leads (id, merchant_id, product_id, product_name, insurer_name, cover_inr, premium_inr, "
               "consent_at, status) VALUES ('INS-1','M004','ELECTRONICS_PARTS','x','x',1000,10,'2026-10-31T00:00:00Z','interested')")
    db.commit()
    assert check(db, policy, make_state, step, "M004")[:2] == ("BLOCK", "OFFER_NOT_ELIGIBLE")
    db.execute("UPDATE insurance_leads SET status='declined', consent_at=NULL, declined_at=? WHERE id='INS-1'",
               (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    db.commit()
    assert check(db, policy, make_state, step, "M004")[:2] == ("BLOCK", "OFFER_COOLING_OFF")
    later = datetime.now(timezone.utc) + timedelta(days=policy["offer_cooling_off_days"] + 1)
    assert check(db, policy, make_state, step, "M004", now=later)[0] == "NEEDS_CONFIRMATION"      # the window passed


def test_the_kill_switch_stops_insurance_at_once(db, policy, make_state, make_step):
    policy["disabled_actions"] = ["offer_insurance"]
    assert check(db, policy, make_state, offer(make_step, "M004", "ELECTRONICS_PARTS"), "M004")[:2] == ("BLOCK", "ACTION_DISABLED")


def test_the_guardrail_reads_the_database_not_the_state(db, policy, make_state, make_step):
    step = offer(make_step, "M004", "ELECTRONICS_PARTS")
    assert check(db, policy, make_state, step, "M004")[0] == "NEEDS_CONFIRMATION"
    db.execute("UPDATE merchants SET business_category = 'grocery' WHERE merchant_id = 'M004'")     # the fit changed
    db.commit()
    assert check(db, policy, make_state, step, "M004")[:2] == ("BLOCK", "OFFER_NOT_ELIGIBLE")


def test_insurance_is_not_a_money_action(policy):
    assert "offer_insurance" not in policy["money_actions"] and "offer_insurance" in policy["consent_required"]
    assert {"check_insurance", "offer_insurance"} <= set(policy["allow_list"])
    assert "check_insurance" in policy["read_only_actions"] and "offer_insurance" not in policy["read_only_actions"]


# ------------------------------------------------------------------ the integration (lead record)

@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "ins.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    conn = connect(path)
    yield conn
    conn.close()


def test_create_lead_records_interest_with_numbers_read_from_the_database_and_is_idempotent(env):
    a = insurance.create_lead("M004", "ELECTRONICS_PARTS", "S1", "S1:3", trace_id="T-1")
    assert a == insurance.create_lead("M004", "ELECTRONICS_PARTS", "S1", "S1:3")        # same key -> same lead
    lead = insurance.get_lead(a)
    assert lead["status"] == "interested" and lead["consent_at"] and lead["cover_inr"] == 650000 and lead["premium_inr"] == 5850
    assert env.execute("SELECT COUNT(*) FROM insurance_leads").fetchone()[0] == 1


def test_create_lead_refuses_a_product_the_rules_do_not_recommend(env):
    with pytest.raises(ValueError):
        insurance.create_lead("M004", "SHOP_FIRE", "S1", "S1:4")
    assert env.execute("SELECT COUNT(*) FROM insurance_leads").fetchone()[0] == 0


def test_the_lead_table_refuses_an_interested_lead_without_consent_time(env):
    with pytest.raises(Exception):
        env.execute("INSERT INTO insurance_leads (id, merchant_id, product_id, product_name, insurer_name, cover_inr, "
                    "premium_inr, status) VALUES ('INS-9','M004','SHOP_FIRE','x','x',1,1,'interested')")


def test_withdraw_lead_rolls_back_by_token(env):
    lead_id = insurance.create_lead("M004", "ELECTRONICS_PARTS", "S1", "S1:5")
    env.execute("INSERT INTO audit_log (trace_id, session_id, merchant_id, actor, step_no, action_type, params_masked, "
                "guardrail_decision, reason_code, reason, rollback_token) VALUES ('t','S1','M004','agent',5,'offer_insurance',"
                "'{}','ALLOW','CONFIRMED_BY_MERCHANT','ok','rb-ins')")
    audit_id = env.execute("SELECT id FROM audit_log").fetchone()[0]
    env.execute("INSERT INTO executions (idempotency_key, audit_id, trace_id, session_id, merchant_id, action_type, "
                "rollback_token, status, result_ref) VALUES ('S1:5',?,'t','S1','M004','offer_insurance','rb-ins','success',?)",
                (audit_id, lead_id))
    env.commit()
    assert insurance.withdraw_lead("rb-ins").ok
    assert insurance.get_lead(lead_id)["status"] == "withdrawn"
    assert not insurance.has_open_lead(env, "M004", "ELECTRONICS_PARTS")


# ------------------------------------------------------------------ the whole conversation (offline: keyword intent + templates)

@pytest.fixture
def loop(env, monkeypatch):
    from chaukas.core import m2_shim, orchestrator
    from chaukas.gateway import session as gw
    from chaukas.llm import prompt as llm_prompt
    from chaukas.llm.client import LLMUnavailable

    def no_llm(*a, **kw):
        raise LLMUnavailable("offline")
    monkeypatch.setattr(llm_prompt, "complete", no_llm)
    monkeypatch.setattr(m2_shim, "emit_span", lambda span: None)

    class Loop:
        db = env

        def session(self, mid):
            return gw.create_session(mid, "chat", "autonomous")["session_id"]

        def say(self, sid, text):
            return orchestrator.handle_message(sid, text)

    return Loop()


def table(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def test_a_device_problem_then_a_yes_records_interest_and_nothing_else(loop):
    sid = loop.session("M017")
    r1 = loop.say(sid, "My QR code is not scanning")
    assert [p.action_type for p in r1.plan] == ["update_ticket", "check_insurance", "offer_insurance"]
    card = r1.pending_confirmation["insurance"]
    assert card["product_id"] == "DEVICE_PROTECT" and card["cover_inr"] == 15000 and card["premium_inr"] == 499
    assert "Rs 15,000" in r1.reply and "Rs 499" in r1.reply and "yes or no" in r1.reply
    assert r1.status.value == "awaiting_confirmation" and not table(loop.db, "SELECT * FROM insurance_leads")

    r2 = loop.say(sid, "yes")
    assert r2.status.value == "completed"                                             # the merchant's request is done
    assert r2.handoff.reason_code == "INSURANCE_INTEREST" and r2.handoff.suggested_step is None
    assert "approv" not in r2.handoff.decision_needed.lower() and "pay" not in r2.handoff.decision_needed.lower()
    assert "No premium was charged" in r2.reply
    lead = table(loop.db, "SELECT * FROM insurance_leads")[0]
    assert (lead["merchant_id"], lead["product_id"], lead["status"]) == ("M017", "DEVICE_PROTECT", "interested")
    assert [r["purpose"] + ":" + r["action"] for r in table(loop.db, "SELECT * FROM consents WHERE merchant_id='M017'")] == \
        ["ai_assistance:granted", "insurance_offer:granted"]
    done = {r["action_type"] for r in table(loop.db, "SELECT * FROM executions WHERE status='success'")}
    assert done == {"update_ticket", "offer_insurance"}                               # no payout, no loan, no premium
    assert table(loop.db, "SELECT reason_code FROM handoffs")[0]["reason_code"] == "INSURANCE_INTEREST"


def test_a_no_records_nothing_as_interest_and_starts_the_cooling_off(loop):
    sid = loop.session("M004")
    loop.say(sid, "Can I get insurance for my shop?")
    r = loop.say(sid, "no")
    assert r.status.value == "completed" and r.handoff is None
    assert [x["status"] for x in table(loop.db, "SELECT * FROM insurance_leads")] == ["declined"]
    assert not table(loop.db, "SELECT * FROM executions WHERE action_type='offer_insurance'")
    assert not [c for c in table(loop.db, "SELECT * FROM consents") if c["purpose"] == "insurance_offer"]
    assert "nothing was recorded" in r.reply
    # a new conversation straight away: not asked again
    r2 = loop.say(loop.session("M004"), "Can I get insurance for my shop?")
    assert [d["reason_code"] for d in r2.decisions if d["action_type"] == "offer_insurance"] == ["OFFER_COOLING_OFF"]
    assert r2.pending_confirmation is None and "not appropriate right now" in r2.reply


def test_after_a_yes_a_second_ask_is_not_offered_again(loop):
    loop.say(sid := loop.session("M004"), "insurance milega kya?")
    loop.say(sid, "haan")
    r = loop.say(loop.session("M004"), "insurance milega kya?")
    assert [d["reason_code"] for d in r.decisions if d["action_type"] == "offer_insurance"] == ["OFFER_NOT_ELIGIBLE"]
    assert len(table(loop.db, "SELECT * FROM insurance_leads")) == 1


def test_support_comes_first_a_failed_settlement_blocks_the_pitch(loop):
    r = loop.say(loop.session("M002"), "insurance milega kya?")
    assert [d["reason_code"] for d in r.decisions if d["action_type"] == "offer_insurance"] == ["ISSUE_UNRESOLVED"]
    assert r.pending_confirmation is None and not table(loop.db, "SELECT * FROM insurance_leads")


def test_a_shop_nothing_fits_is_told_so_honestly(loop):
    r = loop.say(loop.session("M003"), "Insurance chahiye")
    assert [p.action_type for p in r.plan] == ["check_insurance"] and r.pending_confirmation is None
    assert "do not have a suitable insurance" in r.reply or "suitable insurance nahi" in r.reply


def test_withdrawn_insurance_consent_stops_the_offer_in_the_next_conversation(loop):
    consent.withdraw(loop.db, "M004", "insurance_offer")
    r = loop.say(loop.session("M004"), "insurance milega kya?")
    assert [d["reason_code"] for d in r.decisions if d["action_type"] == "offer_insurance"] == ["CONSENT_WITHDRAWN"]
    assert r.pending_confirmation is None


def test_hinglish_reply_when_the_merchant_writes_hinglish(loop):
    r = loop.say(loop.session("M004"), "Shop ke liye insurance milega kya?")
    assert "Haan ya nahi" in r.reply and "Rs 650,000" in r.reply and "Rs 5,850" in r.reply


def test_insurance_never_touches_the_loan_or_payout_machinery(loop):
    sid = loop.session("M005")
    loop.say(sid, "Mujhe shop ka insurance chahiye")
    loop.say(sid, "haan")
    assert not table(loop.db, "SELECT * FROM offers WHERE status IN ('accepted','offered')")
    assert not table(loop.db, "SELECT * FROM executions WHERE action_type IN ('retrigger_payout','create_offer')")


def test_the_loan_flow_is_unchanged_by_the_insurance_hooks(loop):
    sid = loop.session("M010")
    r = loop.say(sid, "Mujhe loan chahiye, kitna mil sakta hai?")
    assert [p.action_type for p in r.plan] == ["check_eligibility", "create_offer"] 
    assert r.pending_confirmation["step"]["action_type"] == "create_offer" and "kfs" in r.pending_confirmation


@pytest.mark.parametrize("text,intent", [
    ("insurance milega kya?", "insurance_inquiry"), ("mujhe bima chahiye", "insurance_inquiry"),
    ("Can I get insurance for my shop?", "insurance_inquiry"), ("Loan milega kya?", "loan_inquiry"),
    ("Mera QR scan nahi ho raha", "device_issue"), ("mera settlement nahi aaya", "settlement_delay"),
])
def test_the_keyword_fallback_knows_insurance_and_still_knows_everything_else(text, intent):
    from chaukas.agents.intent import keyword_classify
    assert keyword_classify(text, pending=False).intent.value == intent


def test_the_consent_api_accepts_the_insurance_purpose(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from chaukas.api import ops
    app = FastAPI()
    app.include_router(ops.router)
    c = TestClient(app)
    body = {"purpose": "insurance_offer", "action": "granted", "channel": "chat"}
    r = c.post("/api/merchants/M004/consents", json=body)
    assert r.status_code == 200 and r.json()["purposes"]["insurance_offer"]["state"] == "granted"
    assert c.post("/api/merchants/M004/consents", json={**body, "action": "withdrawn"}).json()["purposes"]["insurance_offer"]["state"] == "withdrawn"
# ------------------------------------------------------------------ fairness (RBI FREE-AI R6)

def test_the_recommendation_ignores_name_language_and_phone_it_uses_only_business_facts(db):
    base = {mid: insurance.recommend(db, mid) for mid in EXPECTED}
    for name, lang in (("Someone Else", "gu-IN"), ("Fatima Begum", "mr-IN"), ("Aarav Kumar", "en-IN")):
        db.execute("UPDATE merchants SET name = ?, preferred_lang = ?, phone = '+910000000000'", (name, lang))
        db.commit()
        assert {mid: insurance.recommend(db, mid) for mid in EXPECTED} == base


def test_the_recommendation_reads_only_business_columns():
    import inspect
    import re
    src = inspect.getsource(insurance.recommend)
    columns = [c.strip() for c in re.search(r"SELECT (.*?) FROM merchants", src, re.S).group(1).split(",")]
    assert columns == ["business_category", "device", "gmv_30d"]          # no name, language, phone, UPI, PAN, account
