"""detect, mask, mask_text, tokenise, detokenise, encrypt, decrypt.
PII_FIELDS must equal config/policy.yaml pii_fields.

Owner: Member 2 · Contract: CONTRACTS C4
"""
import hashlib
import re
import secrets
from typing import Any

PII_FIELDS: list[str] = ["account_no", "ifsc", "vpa", "pan", "aadhaar", "phone", "name"]

TOKEN_PREFIX = "tok_"

# Free-text patterns. Order matters in mask_text: vpa first (it can contain digits),
# then ifsc / pan / aadhaar, then phone (10 digits, separators allowed), then account_no (9-18 digits).
# Amounts (e.g. 32500, 1,00,000) and ids (SET-99213) are shorter than 9 digits and never match.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("vpa", re.compile(r"(?<![\w.@-])[\w.\-]{2,}@[A-Za-z][A-Za-z0-9]*")),
    # ifsc / pan: merchants type lowercase too. A PAN that is already masked (XXXXX1037H) is not PII any more.
    ("ifsc", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{4}0[A-Za-z0-9]{6}(?![A-Za-z0-9])")),
    ("pan", re.compile(r"(?<![A-Za-z0-9])(?!(?i:x{5}))[A-Za-z]{5}\d{4}[A-Za-z](?![A-Za-z0-9])")),
    ("aadhaar", re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)")),
    # phone: 10 digits, optionally +91 and a space or hyphen in the middle (98000 00001, +91 98000-00001)
    ("phone", re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")),
    ("account_no", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),
]

# token -> raw value. In-memory only: tokens are valid for the life of the process.
_VAULT: dict[str, str] = {}
_SALT = secrets.token_hex(16)  # per-process, so tokens cannot be precomputed from a value


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def mask(value: str, field: str) -> str:
    """Display / log form of one PII value (formats: system design B7.3). Idempotent."""
    value = str(value)
    if value.startswith(TOKEN_PREFIX):
        return value  # tokens are already safe
    if field == "name":
        return value[:2] + "****" if len(value) > 2 else value[:1] + "****"
    if field == "phone":
        return "XXXXXX" + _digits(value)[-4:]
    if field == "account_no":
        return "XXXXXX" + _digits(value)[-4:]
    if field == "aadhaar":
        return "XXXXXXXX" + _digits(value)[-4:]
    if field == "pan":
        return "XXXXX" + value[5:]
    if field == "ifsc":
        return value[:5] + "******"
    if field == "vpa":
        handle = value.split("@", 1)[1] if "@" in value else ""
        return value[:1] + "****" + ("@" + handle if handle else "")
    return "****"  # unknown field: hide everything rather than leak


def detect(obj: Any) -> list[str]:
    """PII field names present in a string (regex) or a dict / list (keys, plus regex on string values)."""
    found: set[str] = set()
    _collect(obj, found)
    return [f for f in PII_FIELDS if f in found]


def _collect(obj: Any, found: set[str]) -> None:
    if isinstance(obj, str):
        for field, rx in _PATTERNS:  # same order as mask_text: a matched span is consumed
            if rx.search(obj):
                found.add(field)
                obj = rx.sub(" ", obj)
    elif isinstance(obj, dict):
        for key, val in obj.items():
            if str(key).lower() in PII_FIELDS:
                found.add(str(key).lower())
            _collect(val, found)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            _collect(item, found)


def mask_text(text: str) -> str:
    """Mask every PII value found inside free text (used at ingestion). Names cannot be found by regex."""
    for field, rx in _PATTERNS:
        text = rx.sub(lambda m, f=field: mask(m.group(0), f), text)
    return text


def tokenise(value: str, field: str) -> str:
    """'tok_{field}_{8 hex}'. Same value + field -> same token within one run."""
    value = str(value)
    attempt = 0
    while True:
        digest = hashlib.sha256(f"{_SALT}|{field}|{value}|{attempt}".encode()).hexdigest()[:8]
        token = f"{TOKEN_PREFIX}{field}_{digest}"
        if _VAULT.setdefault(token, value) == value:
            return token
        attempt += 1  # 32-bit collision with a different value: try again


def detokenise(token: str) -> str:
    """Raw value behind a token. ONLY chaukas/agents/action.py may call this (CLAUDE.md rule 5)."""
    try:
        return _VAULT[token]
    except KeyError:
        raise KeyError("unknown or expired token") from None


def encrypt(value: str) -> bytes:
    """Prototype passthrough. Prod: field-level encryption with keys kept outside the DB."""
    return value.encode("utf-8")


def decrypt(blob: bytes) -> str:
    return blob.decode("utf-8")
