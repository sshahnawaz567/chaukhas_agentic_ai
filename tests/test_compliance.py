"""AI disclosure + DPDP notice (R1, D1, L5) and consent artefacts (D2, D3, L1).

Owner: Member 2 · Contract: COMPLIANCE.md
"""
import json
import re
import sqlite3

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chaukas.api import ops
from chaukas.compliance import consent, disclosure
from chaukas.db import ROOT, connect
from data.seed import seed

MERCHANTS = json.loads((ROOT / "data" / "merchant_fixtures.json").read_text(encoding="utf-8"))["merchants"]
CONFIG = yaml.safe_load(disclosure.CONFIG_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ disclosure

@pytest.mark.parametrize("lang", disclosure.supported_languages())
def test_every_language_discloses_that_it_is_an_ai(lang):
    d = disclosure.get_disclosure_details(lang)
    assert d.lang == lang
    assert "AI" in d.ai_disclosure and "Paytm" in d.ai_disclosure


def test_demo_scene_1_first_message_is_the_exact_line():
    d = disclosure.get_disclosure_details("hi-Latn")
    assert d.ai_disclosure == "Namaste! Main Chaukas hoon, Paytm ka AI assistant."
    assert d.message.startswith(d.ai_disclosure)


@pytest.mark.parametrize("lang", ["hi-Latn", "hi-IN", "en-IN", "ta-IN"])
def test_notice_covers_what_why_rights_human_and_grievance(lang):
    d = disclosure.get_disclosure_details(lang)
    assert d.grievance_contact in d.notice and d.notice_url in d.notice       # D8 / L5
    assert "{" not in d.notice and "}" not in d.notice                         # placeholders all filled


def test_english_notice_names_each_required_element():
    n = disclosure.get_disclosure_details("en-IN").notice.lower()
    for needed in ("name", "bank account", "loan offers", "masked", "erase", "withdraw", "person", "grievances"):
        assert needed in n, needed


def test_languages_without_a_notice_fall_back_to_english_notice():
    d = disclosure.get_disclosure_details("ta-IN")
    assert d.notice == disclosure.get_disclosure_details("en-IN").notice
    assert d.ai_disclosure != disclosure.get_disclosure_details("en-IN").ai_disclosure


@pytest.mark.parametrize("asked,expected", [
    ("hi-IN", "hi-IN"), ("hi", "hi-IN"), ("ta", "ta-IN"), ("hi-Latn", "hi-Latn"),
    ("or-IN", CONFIG["fallback_lang"]), (None, CONFIG["fallback_lang"]), ("", CONFIG["fallback_lang"]),
])
def test_language_resolution(asked, expected):
    assert disclosure.resolve_language(asked) == expected


def test_every_fixture_merchant_language_gets_a_disclosure():
    for m in MERCHANTS:
        assert disclosure.get_disclosure_details(m["preferred_lang"]).lang == m["preferred_lang"], m["merchant_id"]


def test_notice_version_changes_when_any_text_changes(tmp_path):
    base = disclosure.notice_version()
    assert re.fullmatch(r"v1-[0-9a-f]{8}", base)
    assert disclosure.notice_version() == base                                  # stable
    edited = tmp_path / "d.yaml"
    cfg = json.loads(json.dumps(CONFIG))
    cfg["messages"]["en-IN"]["notice"] += " extra"
    edited.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert disclosure.notice_version(edited) != base


def test_pitch_rule_no_compliant_or_certified_claims_in_user_facing_text():
    blob = disclosure.disclosure_message("en-IN").lower() + yaml.safe_dump(CONFIG).lower()
    for banned in ("rbi-compliant", "rbi compliant", "certified"):
        assert banned not in blob


def test_gateway_shape_is_text_and_version_tuple():
    """Member 1's m2_shim does: text, notice_version = get_disclosure(lang)."""
    text, version = disclosure.get_disclosure("hi-Latn")
    assert text.startswith("Namaste! Main Chaukas hoon") and version == disclosure.notice_version()
    assert isinstance(text, str) and isinstance(version, str)


# ------------------------------------------------------------------ consent

@pytest.fixture
def conn(tmp_path):
    seed(tmp_path / "c.db")
    c = connect(tmp_path / "c.db")
    yield c
    c.close()


def test_never_asked_means_no_consent(conn):
    assert not consent.has_consent(conn, "M001", "ai_assistance")
    assert consent.current_state(conn, "M001")["ai_assistance"]["state"] is None


def test_grant_then_withdraw_is_a_trail_not_an_overwrite(conn):
    consent.grant(conn, "M001", "ai_assistance", session_id="S1")
    assert consent.has_consent(conn, "M001", "ai_assistance")
    consent.withdraw(conn, "M001", "ai_assistance", session_id="S1")
    assert not consent.has_consent(conn, "M001", "ai_assistance")                # next turn respects it (D3)
    consent.grant(conn, "M001", "ai_assistance")                                 # and it can come back
    assert [h["action"] for h in consent.history(conn, "M001")] == ["granted", "withdrawn", "granted"]


def test_notice_version_is_recorded(conn):
    consent.grant(conn, "M001", "ai_assistance")
    assert consent.history(conn, "M001")[0]["notice_version"] == disclosure.notice_version()


def test_repeating_the_same_action_does_not_add_a_row(conn):
    first = consent.grant(conn, "M001", "ai_assistance")
    assert consent.grant(conn, "M001", "ai_assistance") == first
    assert len(consent.history(conn, "M001")) == 1


def test_purposes_and_merchants_are_independent(conn):
    consent.grant(conn, "M001", "ai_assistance")
    consent.grant(conn, "M001", "loan_offer", kfs_shown=True)
    consent.withdraw(conn, "M001", "loan_offer")
    assert consent.has_consent(conn, "M001", "ai_assistance") and not consent.has_consent(conn, "M001", "loan_offer")
    assert not consent.has_consent(conn, "M002", "ai_assistance")


def test_loan_consent_is_invalid_before_the_kfs_was_shown(conn):
    with pytest.raises(consent.ConsentError, match="KFS"):
        consent.grant(conn, "M001", "loan_offer")
    assert consent.history(conn, "M001") == []
    consent.withdraw(conn, "M001", "loan_offer")                                 # withdrawing never needs the KFS


def test_unknown_purpose_or_action_rejected(conn):
    with pytest.raises(consent.ConsentError):
        consent.record(conn, "M001", "marketing", "granted")
    with pytest.raises(consent.ConsentError):
        consent.record(conn, "M001", "ai_assistance", "maybe")


def test_unknown_merchant_is_rejected_by_the_database(conn):
    with pytest.raises(sqlite3.IntegrityError):
        consent.grant(conn, "M999", "ai_assistance")


def test_consents_table_refuses_updates(conn):
    consent.grant(conn, "M001", "ai_assistance")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE consents SET action = 'withdrawn'")


def test_consents_table_refuses_deletes(conn):
    consent.grant(conn, "M001", "ai_assistance")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM consents")
    assert len(consent.history(conn, "M001")) == 1


def test_is_withdrawn_only_after_an_explicit_withdrawal(conn):
    assert not consent.is_withdrawn(conn, "M001", "loan_offer")                 # never asked
    consent.grant(conn, "M001", "loan_offer", kfs_shown=True)
    assert not consent.is_withdrawn(conn, "M001", "loan_offer")
    consent.withdraw(conn, "M001", "loan_offer")
    assert consent.is_withdrawn(conn, "M001", "loan_offer")


def test_code_never_updates_or_deletes_consents():
    """CLAUDE.md rule 6, checked on the source: no UPDATE/DELETE against consents (or audit_log) anywhere."""
    offenders = []
    for py in (ROOT / "chaukas").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if re.search(r"(UPDATE|DELETE\s+FROM)\s+(consents|audit_log)\b", text, re.I):
            offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, offenders


# ------------------------------------------------------------------ API

@pytest.fixture
def client(tmp_path, monkeypatch):
    seed(tmp_path / "api.db")
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(tmp_path / "api.db"))
    app = FastAPI()
    app.include_router(ops.router)
    return TestClient(app)


def test_api_disclosure(client):
    body = client.get("/api/disclosure", params={"lang": "ta"}).json()
    assert body["lang"] == "ta-IN" and body["notice_version"] == disclosure.notice_version()
    assert body["message"].startswith(body["ai_disclosure"])
    assert client.get("/api/disclosure").json()["lang"] == CONFIG["fallback_lang"]


def test_api_consent_grant_and_withdraw_flow(client):
    url = "/api/merchants/M001/consents"
    assert client.get(url).json()["purposes"]["ai_assistance"]["state"] is None

    r = client.post(url, json={"purpose": "ai_assistance", "action": "granted"})
    assert r.json()["purposes"]["ai_assistance"]["state"] == "granted"
    r = client.post(url, json={"purpose": "ai_assistance", "action": "withdrawn"})
    assert r.json()["purposes"]["ai_assistance"]["state"] == "withdrawn"


def test_api_loan_consent_needs_kfs_and_errors_use_the_c5_shape(client):
    url = "/api/merchants/M001/consents"
    bad = client.post(url, json={"purpose": "loan_offer", "action": "granted"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "CONSENT_INVALID"
    ok = client.post(url, json={"purpose": "loan_offer", "action": "granted", "kfs_shown": True})
    assert ok.json()["purposes"]["loan_offer"]["state"] == "granted"


def test_api_unknown_merchant_and_bad_purpose(client):
    assert client.get("/api/merchants/M999/consents").json()["error"]["code"] == "MERCHANT_NOT_FOUND"
    assert client.post("/api/merchants/M999/consents",
                       json={"purpose": "ai_assistance", "action": "granted"}).status_code == 404
    assert client.post("/api/merchants/M001/consents", json={"purpose": "marketing", "action": "granted"}).status_code == 422
