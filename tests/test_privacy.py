"""mask/tokenise/scrub + PII-leak test.

Owner: Member 2 · Contract: CONTRACTS C4
"""
import json
import re
from pathlib import Path

import pytest
import yaml

from chaukas.privacy.pii import (
    PII_FIELDS, decrypt, detect, detokenise, encrypt, mask, mask_text, tokenise,
)
from chaukas.privacy.scrub import scrub

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = json.loads((ROOT / "data" / "merchant_fixtures.json").read_text(encoding="utf-8"))["merchants"]
M001 = FIXTURES[0]["pii"] | {"name": FIXTURES[0]["name"]}


def test_pii_fields_match_policy_yaml():
    policy = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text(encoding="utf-8"))
    assert PII_FIELDS == policy["pii_fields"]


# ---------- mask: one format per field (system design B7.3) ----------

@pytest.mark.parametrize("field,expected", [
    ("name", "Sh****"),
    ("phone", "XXXXXX0001"),
    ("vpa", "s****@paytm"),
    ("pan", "XXXXX1037H"),
    ("account_no", "XXXXXX7919"),
    ("ifsc", "SBIN0******"),
])
def test_mask_formats(field, expected):
    assert mask(M001[field], field) == expected


def test_mask_aadhaar_and_unknown_field():
    assert mask("1234 5678 9012", "aadhaar") == "XXXXXXXX9012"
    assert mask("anything", "mystery") == "****"  # unknown field hides everything


@pytest.mark.parametrize("field", PII_FIELDS)
def test_mask_is_idempotent(field):
    sample = {"name": "Sharma", "phone": "+919800000001", "vpa": "abc@paytm", "pan": "ABAPS1037H",
              "account_no": "501001007919", "ifsc": "SBIN0001237", "aadhaar": "123456789012"}[field]
    once = mask(sample, field)
    assert mask(once, field) == once


def test_mask_leaves_tokens_alone():
    tok = tokenise("501001007919", "account_no")
    assert mask(tok, "account_no") == tok


# ---------- mask_text / detect ----------

def test_mask_text_hides_every_pii_kind_in_free_text():
    text = (f"mera account {M001['account_no']} hai, phone {M001['phone']}, pan {M001['pan']}, "
            f"ifsc {M001['ifsc']}, upi {M001['vpa']}, aadhaar 1234 5678 9012")
    out = mask_text(text)
    for raw in (M001["account_no"], M001["phone"], M001["pan"], M001["ifsc"], M001["vpa"], "1234 5678 9012"):
        assert raw not in out
    assert "XXXXXX7919" in out and "SBIN0******" in out


def test_mask_text_keeps_amounts_and_ids():
    text = "SET-99213 ka 32500 aur 1,00,000 bhejo, ticket TKT-77201, 2026-10-31T09:15:00Z"
    assert mask_text(text) == text


def test_mask_text_phone_without_country_code():
    assert "9800000001" not in mask_text("call 9800000001 now")


def test_detect_text_and_dict():
    assert detect("hello world 32500") == []
    assert detect(f"pan {M001['pan']} phone {M001['phone']}") == ["pan", "phone"]
    assert detect({"settlement_id": "SET-1", "meta": {"account_no": "x"}, "rows": [{"vpa": "a@b"}]}) == ["account_no", "vpa"]


# ---------- tokenise / detokenise / encrypt ----------

def test_token_format_and_determinism():
    t1 = tokenise("501001007919", "account_no")
    assert re.fullmatch(r"tok_account_no_[0-9a-f]{8}", t1)
    assert tokenise("501001007919", "account_no") == t1
    assert tokenise("501001007919", "phone") != t1  # field is part of the token


def test_detokenise_roundtrip_and_unknown_token():
    t = tokenise(M001["account_no"], "account_no")
    assert detokenise(t) == M001["account_no"]
    with pytest.raises(KeyError):
        detokenise("tok_account_no_00000000")


def test_encrypt_decrypt_roundtrip():
    assert decrypt(encrypt("हेलो 123")) == "हेलो 123"


# ---------- scrub ----------

def test_scrub_masks_pii_keys_and_text_recursively_without_mutating():
    original = {
        "account_no": M001["account_no"],
        "name": M001["name"],
        "step": {"params": {"issue": f"mera pan {M001['pan']} galat hai", "amount": 18400}},
        "rows": [{"phone": M001["phone"]}, ("x", M001["vpa"])],
    }
    snapshot = json.dumps(original, sort_keys=True)
    out = scrub(original)
    assert json.dumps(original, sort_keys=True) == snapshot  # input untouched
    dumped = json.dumps(out)
    for raw in M001.values():
        assert raw not in dumped
    assert out["step"]["params"]["amount"] == 18400  # money stays as int
    assert out["account_no"] == "XXXXXX7919"


def test_scrub_pydantic_model_and_scalars():
    from pydantic import BaseModel

    class P(BaseModel):
        phone: str
        amount: int

    assert scrub(P(phone=M001["phone"], amount=5)) == {"phone": "XXXXXX0001", "amount": 5}
    assert scrub(None) is None and scrub(7) == 7 and scrub(True) is True


# ---------- the PII-leak test (gate, DPDP D5/D9) ----------

def test_no_fixture_pii_survives_scrub():
    """Every raw PII value of all 20 merchants must be gone after scrub, as a dict value and inside text."""
    for m in FIXTURES:
        raws = list(m["pii"].values())
        payload = {"merchant": m["pii"], "text": "details: " + " | ".join(raws), "list": raws}
        dumped = json.dumps(scrub(payload), ensure_ascii=False)
        for raw in raws:
            assert raw not in dumped, f"{m['merchant_id']}: raw PII {raw!r} leaked through scrub"


def test_only_action_agent_calls_detokenise():
    """CLAUDE.md rule 5: detokenise() may be CALLED only from chaukas/agents/action.py.
    Looks at real call expressions, so comments, docstrings and the m2_shim wrapper definition do not count."""
    import ast

    allowed = {Path("chaukas/agents/action.py")}
    offenders = []
    for py in (ROOT / "chaukas").rglob("*.py"):
        rel = py.relative_to(ROOT)
        if rel in allowed:
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if name == "detokenise":
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"detokenise() called outside action.py: {offenders}"
