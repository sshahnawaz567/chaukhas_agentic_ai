"""Device upgrade (DEVICE_UPGRADE_PLAN.md): simulated device advisor thresholds, reactive and proactive flows with
Member 2's REAL guardrail, cooling-off shared with loans, one sales offer per conversation. No network.

Owner: Member 1 · Contract: CONTRACTS C1 / C3
"""
import pytest

from chaukas import db
from chaukas.core import event_watcher, m2_shim, orchestrator
from chaukas.core.models import TurnStatus
from chaukas.gateway import session as gw
from chaukas.integrations import devices
from data.seed import seed


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    path = tmp_path / "device.db"
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


def run_sql(sql, *args):
    conn = db.connect()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def pattern(mid, *, gmv, txn, active, device="qr"):
    run_sql("UPDATE merchants SET gmv_30d=?, device=? WHERE merchant_id=?", gmv, device, mid)
    run_sql("UPDATE cashflow_features SET txn_count_30d=?, active_days_30d=? WHERE merchant_id=?", txn, active, mid)


def session(mid):
    return gw.create_session(mid, "chat", "autonomous")["session_id"]


# ------------------------------------------------------------------ the advisor
@pytest.mark.parametrize("mid,to", [("M003", "ai_soundbox"), ("M016", "ai_soundbox"), ("M020", "ai_soundbox"),
                                    ("M021", "pos"), ("M013", "pos"), ("M012", "pos")])
def test_advisor_on_the_fixtures(mid, to):
    a = devices.advise(mid)
    assert a.recommended and a.to_device == to


@pytest.mark.parametrize("mid", ["M008", "M011", "M017", "M001", "M010"])
def test_advisor_says_no_upgrade(mid):
    assert devices.advise(mid).recommended is False


@pytest.mark.parametrize("avg_bill,expected", [(399, "ai_soundbox"), (400, "ai_soundbox"), (401, None),
                                               (499, None), (500, "pos")])
def test_avg_bill_boundaries(avg_bill, expected):
    pattern("M003", gmv=avg_bill * 200, txn=200, active=25)   # 8 payments/day
    a = devices.advise("M003")
    assert (a.to_device if a.recommended else None) == expected


@pytest.mark.parametrize("txn,active,expected", [(174, 25, False), (175, 25, True)])   # 6.96 vs 7.0 per day
def test_payments_per_day_boundary(txn, active, expected):
    pattern("M003", gmv=txn * 150, txn=txn, active=active)
    assert devices.advise("M003").recommended is expected


def test_low_activity_is_never_an_upgrade():
    pattern("M003", gmv=150 * 300, txn=300, active=19)
    a = devices.advise("M003")
    assert not a.recommended and "LOW_ACTIVITY" in a.reason_codes


@pytest.mark.parametrize("text,wanted", [
    ("Mujhe naya soundbox chahiye", True), ("Card machine chahiye, POS milega kya?", True),
    ("Can I get a card machine for my shop?", True), ("मुझे नई मशीन चाहिए", True),
    ("Mera QR scan nahi ho raha", False), ("Soundbox kaam nahi kar raha", False), ("Loan milega kya?", False),
])
def test_upgrade_words_vs_complaints(text, wanted):
    assert devices.wants_device_upgrade(text) is wanted


# ------------------------------------------------------------------ reactive flow, REAL guardrail
def test_reactive_request_after_the_yes():
    sid = session("M003")
    r1 = orchestrator.handle_message(sid, "Mujhe naya soundbox chahiye")
    assert r1.intent.value == "device_upgrade" and r1.status == TurnStatus.AWAITING_CONFIRMATION
    offer = r1.pending_confirmation["device_offer"]
    assert (offer["from_device"], offer["to_device"], offer["avg_bill_inr"], offer["txn_count_30d"]) == \
        ("qr", "ai_soundbox", 150, 280)
    assert "280" in r1.reply and "150" in r1.reply
    assert not rows("SELECT * FROM device_offers") and not rows("SELECT * FROM tickets WHERE session_id=?", sid)

    r2 = orchestrator.handle_message(sid, "haan")
    assert r2.status == TurnStatus.COMPLETED and r2.decisions[-1]["reason_code"] == "CONFIRMED_BY_MERCHANT"
    req = rows("SELECT * FROM device_offers WHERE merchant_id='M003'")[0]
    assert req["status"] == "accepted" and req["to_device"] == "ai_soundbox" and req["offer_shown_at"]
    ticket = rows("SELECT * FROM tickets WHERE id=?", req["ticket_id"])[0]
    assert "AI Soundbox" in ticket["issue"] and ticket["status"] == "open"
    assert r2.handoff.reason_code == "DEVICE_UPGRADE_REQUESTED" and req["ticket_id"] in r2.reply
    assert rows("SELECT ticket_id FROM handoffs WHERE reason_code='DEVICE_UPGRADE_REQUESTED'")[0]["ticket_id"] == req["ticket_id"]
    assert rows("SELECT purpose FROM consents WHERE session_id=? AND purpose='device_offer'", sid)
    assert rows("SELECT outcome FROM sessions WHERE session_id=?", sid)[0]["outcome"] == "resolved_autonomously"


def test_the_advisor_decides_the_device_not_the_merchants_words():
    """M021 asks for a soundbox but its pattern says POS: the request is for what the data supports."""
    r = orchestrator.handle_message(session("M021"), "Mujhe naya soundbox chahiye")
    assert r.pending_confirmation["step"]["params"]["to_device"] == "pos"


def test_decline_starts_the_shared_cooling_off_for_loans_too():
    sid = session("M021")
    orchestrator.handle_message(sid, "Can I get a card machine for my shop?")
    r = orchestrator.handle_message(sid, "nahi")
    assert r.status == TurnStatus.COMPLETED and r.handoff is None and not rows("SELECT * FROM executions")
    assert rows("SELECT status FROM device_offers WHERE merchant_id='M021'")[0]["status"] == "declined"
    loan = orchestrator.handle_message(session("M021"), "Loan milega kya?")   # M021 is loan-eligible (30,000)
    assert [(d["action_type"], d["reason_code"]) for d in loan.decisions][-1] == ("create_offer", "OFFER_COOLING_OFF")


def test_open_issue_blocks_the_device_offer():
    r = orchestrator.handle_message(session("M013"), "POS machine milegi kya?")
    assert r.decisions[-1]["verdict"] == "BLOCK" and r.decisions[-1]["reason_code"] == "ISSUE_UNRESOLVED"
    assert not rows("SELECT * FROM device_offers") and r.status == TurnStatus.COMPLETED


def test_one_sales_offer_per_conversation():
    sid = session("M021")
    orchestrator.handle_message(sid, "Can I get a card machine for my shop?")
    orchestrator.handle_message(sid, "haan")
    r = orchestrator.handle_message(sid, "Loan milega kya?")
    assert [p.action_type for p in r.plan] == ["check_eligibility"] and r.pending_confirmation is None


def test_a_device_complaint_is_still_a_support_ticket():
    r = orchestrator.handle_message(session("M017"), "Mera QR scan nahi ho raha")
    assert r.intent.value == "device_issue" and "request_device_upgrade" not in [p.action_type for p in r.plan]


# ------------------------------------------------------------------ proactive (automation)
def test_device_scan_nudges_and_waits_for_the_yes():
    hits = event_watcher.scan("M003", "device_upgrade")
    assert len(hits) == 1 and hits[0]["to_device"] == "ai_soundbox"
    t = hits[0]["turn"]
    assert t.status == TurnStatus.AWAITING_CONFIRMATION and "280" in t.reply and "150" in t.reply
    assert not rows("SELECT * FROM device_offers") and not rows("SELECT * FROM executions")
    assert rows("SELECT trigger_source, trigger_ref FROM sessions WHERE session_id=?", t.session_id)[0] == \
        {"trigger_source": "proactive", "trigger_ref": "device_upgrade:M003:ai_soundbox"}

    r = orchestrator.handle_confirm(t.session_id, t.pending_confirmation["pending_audit_id"], True, "consent",
                                    None, "merchant", None)
    assert r.status == TurnStatus.COMPLETED and rows("SELECT status FROM device_offers")[0]["status"] == "accepted"


def test_device_scan_dedupes_and_respects_gating():
    assert len(event_watcher.scan("M020", "device_upgrade")) == 1
    assert event_watcher.scan("M020", "device_upgrade") == []           # nudged once
    assert event_watcher.scan("M013", "device_upgrade") == []           # failed settlement: support first
    assert event_watcher.scan("M018", "device_upgrade") == []           # declined offer: cooling-off
    assert event_watcher.scan("M008", "device_upgrade") == []           # nothing to recommend


def test_a_settlement_scan_never_sends_a_sales_nudge():
    hits = event_watcher.scan(None)                                     # default kind: settlement_failed
    assert hits and all("settlement_id" in h and "to_device" not in h for h in hits)
    assert not rows("SELECT * FROM sessions WHERE trigger_ref LIKE 'device_upgrade:%'")


def test_scan_api_takes_the_kind():
    from fastapi.testclient import TestClient
    client = TestClient(__import__("chaukas.main", fromlist=["app"]).app)
    body = client.post("/api/events/scan", json={"merchant_id": "M016", "kind": "device_upgrade"}).json()
    assert body[0]["kind"] == "device_upgrade" and body[0]["to_device"] == "ai_soundbox"
    assert client.post("/api/events/scan", json={"kind": "robot"}).status_code == 422
