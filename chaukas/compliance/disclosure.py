"""AI disclosure + DPDP notice text, per language (first message of every session):
"you are talking to an AI", what data is used and why, that a human is available,
how to raise a grievance.

Owner: Member 2 (text) / Member 3 (UI badge) · COMPLIANCE.md D1, D2, R1

The wording lives in config/disclosure.yaml, never in code. Member 1's gateway calls
`get_disclosure(lang) -> (text, notice_version)` for the first message of a session.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from chaukas.db import ROOT

CONFIG_PATH = ROOT / "config" / "disclosure.yaml"
NOTICE_LANG = "en-IN"          # the notice language used when a language has only the AI line


@dataclass(frozen=True)
class Disclosure:
    lang: str                  # the language actually used (after fallback)
    ai_disclosure: str         # "I am Chaukas, Paytm's AI assistant."
    notice: str                # DPDP notice: data used, purpose, rights, human, grievance
    grievance_contact: str
    notice_url: str
    notice_version: str
    reviewed: bool = True      # False = machine-written text no native speaker has read yet (config unreviewed_languages)

    @property
    def message(self) -> str:
        """The full first message of a session."""
        return f"{self.ai_disclosure}\n\n{self.notice}"


def _load(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def supported_languages(path: Path | None = None) -> list[str]:
    return list(_load(path)["messages"])


def resolve_language(lang: str | None, path: Path | None = None) -> str:
    """Pick the language to use: exact match, then same base language ('hi' -> 'hi-IN'), then the fallback."""
    cfg = _load(path)
    messages = cfg["messages"]
    if lang in messages:
        return lang
    base = (lang or "").split("-")[0].lower()
    # 'hi' means the regional script (hi-IN), not the Roman-script variant (hi-Latn), so -IN codes go first
    for code in sorted(messages, key=lambda c: not c.endswith("-IN")):
        if base and code.split("-")[0].lower() == base:
            return code
    return cfg["fallback_lang"]


def notice_version(path: Path | None = None) -> str:
    """'v1-<8 hex>': the configured version label plus a hash of EVERY text in the file.
    Change a single word and the version changes, so consents.notice_version names the exact wording shown."""
    cfg = _load(path)
    texts = "".join(
        f"{code}|{m.get('ai_disclosure', '')}|{m.get('notice', '')}"
        for code, m in sorted(cfg["messages"].items())
    ) + cfg["grievance_contact"] + cfg["notice_url"]
    return f"{cfg['version']}-{hashlib.sha256(texts.encode('utf-8')).hexdigest()[:8]}"


def get_disclosure_details(lang: str | None = None, path: Path | None = None) -> Disclosure:
    cfg = _load(path)
    used = resolve_language(lang, path)
    entry = cfg["messages"][used]
    notice = entry.get("notice") or cfg["messages"][NOTICE_LANG]["notice"]
    fields = {"grievance_contact": cfg["grievance_contact"], "notice_url": cfg["notice_url"]}
    return Disclosure(
        lang=used, ai_disclosure=entry["ai_disclosure"], notice=notice.format(**fields),
        grievance_contact=cfg["grievance_contact"], notice_url=cfg["notice_url"],
        notice_version=notice_version(path), reviewed=used not in (cfg.get("unreviewed_languages") or []),
    )


def get_disclosure(lang: str | None = None) -> tuple[str, str]:
    """(first-message text, notice_version). This is the shape Member 1's gateway (m2_shim) expects."""
    d = get_disclosure_details(lang)
    return d.message, d.notice_version


def disclosure_message(lang: str | None = None) -> str:
    """Text of the first message of a session, in the merchant's language."""
    return get_disclosure_details(lang).message
