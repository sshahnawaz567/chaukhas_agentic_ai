"""The quick-reply chips of every merchant, and the five final languages.

Owner: Member 2 (data/merchant_fixtures.json, config/disclosure.yaml, chaukas/api/ops.py)

Why this exists: the UI showed the SAME two chips for every merchant after the first few, so the demo of most
scenarios started from a message that did not fit. Each merchant now carries chips for its own scenario, served by
GET /api/merchants/{id}/demo-messages, and every chip is run through the real loop to prove it reaches the intent it
promises. The same file pins the language decision: Hindi, English, Marathi, Hinglish, Gujarati.
"""
import json
import re

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chaukas.api import ops
from chaukas.compliance import disclosure
from chaukas.core.models import Intent
from chaukas.db import ROOT
from data.seed import seed

FIXTURES = json.loads((ROOT / "data" / "merchant_fixtures.json").read_text(encoding="utf-8"))["merchants"]
FINAL_LANGUAGES = {"hi-IN", "en-IN", "mr-IN", "hi-Latn", "gu-IN"}       # Hindi, English, Marathi, Hinglish, Gujarati
REMOVED = ["ta-IN", "te-IN", "ml-IN", "bn-IN", "pa-IN", "ta", "te", "ml", "bn", "pa"]
CHIP_LANGS = ("hi-Latn", "en-IN")
ALL_CHIPS = [(m["merchant_id"], lang, i, chip) for m in FIXTURES for lang in CHIP_LANGS
             for i, chip in enumerate(m["demo_messages"][lang])]


# ------------------------------------------------------------------ the five final languages

def test_the_disclosure_config_has_exactly_the_five_final_languages():
    config = yaml.safe_load((ROOT / "config" / "disclosure.yaml").read_text(encoding="utf-8"))
    assert set(config["messages"]) == FINAL_LANGUAGES
    assert set(disclosure.supported_languages()) == FINAL_LANGUAGES


def test_every_merchant_prefers_one_of_the_final_languages():
    assert {m["preferred_lang"] for m in FIXTURES} <= FINAL_LANGUAGES
    # the demo still shows all five
    assert {m["preferred_lang"] for m in FIXTURES} == FINAL_LANGUAGES


@pytest.mark.parametrize("removed", REMOVED)
def test_a_removed_language_falls_back_to_one_full_notice_in_hindi(removed):
    """No half Telugu, half English bubble any more: the merchant gets the complete Hindi notice."""
    d = disclosure.get_disclosure_details(removed)
    hindi = disclosure.get_disclosure_details("hi-IN")
    assert d.lang == "hi-IN" and d.ai_disclosure == hindi.ai_disclosure and d.notice == hindi.notice


@pytest.mark.parametrize("asked,expected", [("mr", "mr-IN"), ("gu", "gu-IN"), ("hi", "hi-IN"), ("en", "en-IN"),
                                           ("hi-Latn", "hi-Latn")])
def test_the_final_languages_resolve_to_themselves(asked, expected):
    assert disclosure.resolve_language(asked) == expected


# ------------------------------------------------------------------ the chips

def test_every_merchant_has_two_chips_in_hinglish_and_in_english():
    for m in FIXTURES:
        assert set(m["demo_messages"]) == set(CHIP_LANGS), m["merchant_id"]
        for lang in CHIP_LANGS:
            chips = m["demo_messages"][lang]
            assert len(chips) == 2 and chips[0]["text"] != chips[1]["text"], (m["merchant_id"], lang)
            for c in chips:
                assert c["text"].strip() and c["intent"] in {i.value for i in Intent}, (m["merchant_id"], c)


def test_the_first_chip_is_not_the_same_for_everybody():
    """The bug: one fixed pair for every merchant. The first chip must follow the merchant's own scenario."""
    first = [m["demo_messages"]["hi-Latn"][0]["text"] for m in FIXTURES]
    assert len(set(first)) >= 18
    assert len({m["demo_messages"]["hi-Latn"][0]["intent"] for m in FIXTURES}) >= 4      # settlement, loan, device, refund


def test_the_hinglish_and_english_chips_ask_the_same_thing():
    for m in FIXTURES:
        for a, b in zip(m["demo_messages"]["hi-Latn"], m["demo_messages"]["en-IN"]):
            assert a["intent"] == b["intent"], m["merchant_id"]


def test_the_amounts_in_a_chip_exist_in_that_merchants_ledger():
    """A chip that names an amount must name one the merchant really has (the agent uses the ledger anyway)."""
    for m in FIXTURES:
        ledger = {s["amount"] for s in m["settlements"]}
        for lang in CHIP_LANGS:
            chip = m["demo_messages"][lang][0]
            text = chip["text"]
            if chip["intent"] != "settlement_delay" or "1,00,000" in text:
                continue          # a loan amount is not a ledger amount; M005's injection amount is deliberately fake
            for n in re.findall(r"(?<![\d,])\d{4,6}(?![\d,])", text):
                assert int(n) in ledger, (m["merchant_id"], n)


# ------------------------------------------------------------------ the endpoint

@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "chips.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    app = FastAPI()
    app.include_router(ops.router)
    return TestClient(app)


def test_api_returns_the_merchants_own_chips(client):
    body = client.get("/api/merchants/M011/demo-messages").json()
    assert body["merchant_id"] == "M011" and body["scenario"] == "refund_out_of_scope_handoff"
    assert body["default_lang"] == "hi-Latn" and set(body["messages"]) == set(CHIP_LANGS)
    assert body["messages"]["hi-Latn"][0]["intent"] == "refund_request"
    assert client.get("/api/merchants/M012/demo-messages").json()["messages"] != body["messages"]


def test_api_unknown_merchant_is_a_404_in_the_contract_shape(client):
    r = client.get("/api/merchants/M999/demo-messages")
    assert r.status_code == 404 and r.json()["error"]["code"] == "MERCHANT_NOT_FOUND"


# ------------------------------------------------------------------ every chip, through the real loop

@pytest.fixture(scope="module")
def loop(tmp_path_factory):
    """Seed a DB and switch the LLM off (keyword intent + templates): this proves the chips work even offline."""
    try:
        from chaukas.core import m2_shim, orchestrator
        from chaukas.gateway import session as gw
        from chaukas.llm import prompt as llm_prompt
        from chaukas.llm.client import LLMUnavailable
    except ImportError as exc:
        pytest.skip(f"orchestrator not importable: {exc}")
    mp = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("chips") / "chips.db"
    seed(path)
    mp.setenv("CHAUKAS_DB_PATH", str(path))
    mp.setenv("CHAUKAS_REPLAY_MODE", "off")

    def no_llm(*a, **kw):
        raise LLMUnavailable("offline")
    mp.setattr(llm_prompt, "complete", no_llm)
    mp.setattr(m2_shim, "emit_span", lambda span: None)
    yield orchestrator, gw
    mp.undo()


@pytest.mark.parametrize("merchant_id,lang,index,chip", ALL_CHIPS,
                         ids=[f"{m}-{l}-{i}" for m, l, i, _ in ALL_CHIPS])
def test_every_chip_reaches_the_intent_it_promises(loop, merchant_id, lang, index, chip):
    orchestrator, gw = loop
    sid = gw.create_session(merchant_id, "chat", "autonomous")["session_id"]
    resp = orchestrator.handle_message(sid, chip["text"])
    assert resp.intent is not None and resp.intent.value == chip["intent"], (chip["text"], resp.intent)
    assert resp.status.value != "failed" and resp.reply.strip()
