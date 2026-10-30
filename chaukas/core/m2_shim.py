"""Seam between Member 1's code and Member 2's modules (privacy, guardrail, trace, disclosure).

Every function here looks up the REAL implementation lazily on each call. While Member 2's file is
still a skeleton (function missing) it falls back to a clearly marked STUB. When Member 2 lands the
real function, it is picked up automatically — no change needed in Member 1's code.

All STUBs below are placeholders (# STUB). They must never be treated as the real safety layer.

Owner: Member 1 (adapter only) · Real owners: Member 2 (privacy/guardrail/trace/disclosure)
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from chaukas import db
from chaukas.core.models import (
    ActionType,
    ConversationState,
    Confirmation,
    Decision,
    PlannedStep,
    ReasonCode,
    Verdict,
)

ROOT = db.ROOT


def _real(module: str, name: str) -> Callable | None:
    """Return module.name if Member 2 has implemented it, else None."""
    try:
        return getattr(importlib.import_module(module), name, None)
    except Exception:  # module missing/broken -> use stub
        return None


# --------------------------------------------------------------------------
# privacy (C4)
# --------------------------------------------------------------------------
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_VPA = re.compile(r"\b[\w.\-]{2,}@[A-Za-z]{2,}\b")
_ACCOUNT = re.compile(r"(?<!\d)\d{9,18}(?!\d)")

_TOKEN_VAULT: dict[str, str] = {}  # STUB vault (in-process); real one lives in privacy/pii.py


def mask_text(text: str) -> str:
    real = _real("chaukas.privacy.pii", "mask_text")
    if real:
        return real(text)
    # STUB: regex masking, enough to keep raw PII out of the prototype's logs/prompts
    out = _VPA.sub("[VPA]", text)
    out = _PAN.sub("[PAN]", out)
    out = _IFSC.sub("[IFSC]", out)
    out = _PHONE.sub("[PHONE]", out)
    out = _ACCOUNT.sub(lambda m: "XXXXXX" + m.group(0)[-4:], out)
    return out


def detect(obj: str | dict) -> list[str]:
    real = _real("chaukas.privacy.pii", "detect")
    if real:
        return real(obj)
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)  # STUB
    found = []
    for field, rx in (("vpa", _VPA), ("pan", _PAN), ("ifsc", _IFSC), ("phone", _PHONE), ("account_no", _ACCOUNT)):
        if rx.search(text):
            found.append(field)
    return found


def mask(value: str, field: str) -> str:
    real = _real("chaukas.privacy.pii", "mask")
    if real:
        return real(value, field)
    if not value:  # STUB
        return value
    if field == "name":
        return value[:2] + "****"
    if field == "account_no":
        return "XXXXXX" + value[-4:]
    return value[:2] + "****"


def tokenise(value: str, field: str) -> str:
    real = _real("chaukas.privacy.pii", "tokenise")
    if real:
        return real(value, field)
    token = f"tok_{field}_{hashlib.sha1(value.encode()).hexdigest()[:8]}"  # STUB
    _TOKEN_VAULT[token] = value
    return token


def detokenise(token: str) -> str:
    """ONLY chaukas/agents/action.py may call this (CLAUDE.md rule 5)."""
    real = _real("chaukas.privacy.pii", "detokenise")
    if real:
        return real(token)
    return _TOKEN_VAULT[token]  # STUB


def scrub(obj: Any) -> Any:
    real = _real("chaukas.privacy.scrub", "scrub")
    if real:
        return real(obj)
    # STUB: deep-mask every string value in the structure
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


# --------------------------------------------------------------------------
# guardrail (C2)
# --------------------------------------------------------------------------
_READ_ONLY = {ActionType.VERIFY_LEDGER.value, ActionType.CHECK_ELIGIBILITY.value}


def _stub_audit(state: ConversationState, step: PlannedStep, verdict: str, code: ReasonCode, reason: str,
                actor: str, token: str | None, confirms: int | None) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            """INSERT INTO audit_log (trace_id, session_id, merchant_id, actor, step_no, action_type,
                   amount, params_masked, guardrail_decision, reason_code, reason, rollback_token,
                   confirms_audit_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (state.trace_id, state.session_id, state.merchant_id, actor, step.step_no,
             step.action_type, step.amount, json.dumps(scrub(step.params), ensure_ascii=False),
             verdict, code.value, reason, token, confirms),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def guardrail_check(step: PlannedStep, state: ConversationState,
                    confirmation: Confirmation | None = None) -> Decision:
    """Delegates to chaukas.agents.guardrail.check once Member 2 lands it.

    # STUB (walking skeleton only, NOT the safety layer): allows everything except the two cases the
    # demo flow needs to be runnable end to end: create_offer -> consent, and a payout above
    # policy.yaml auto_limit_inr -> step-up. It does NOT implement checks 1-7 (ledger match, never-allowed,
    # gating, daily limit, ...). Member 2's real check() replaces this automatically.
    """
    real = _real("chaukas.agents.guardrail", "check")
    if real:
        return real(step, state, confirmation)

    if step.action_type in _READ_ONLY:
        return Decision(verdict=Verdict.ALLOW, reason_code=ReasonCode.WITHIN_POLICY,
                        reason="STUB guardrail: read-only", audit_id=None, rollback_token=None)

    if confirmation is not None:
        code = ReasonCode.APPROVED_BY_HUMAN if confirmation.actor == "human" else ReasonCode.CONFIRMED_BY_MERCHANT
        actor = confirmation.actor
    else:
        from chaukas.integrations._common import load_config

        limit = int(load_config("policy").get("auto_limit_inr", 25000))
        if step.action_type == ActionType.CREATE_OFFER.value:
            aid = _stub_audit(state, step, "NEEDS_CONFIRMATION", ReasonCode.CONSENT_REQUIRED,
                              "STUB guardrail: offer needs consent", "agent", None, None)
            return Decision(verdict=Verdict.NEEDS_CONFIRMATION, reason_code=ReasonCode.CONSENT_REQUIRED,
                            reason="STUB guardrail: offer needs consent", audit_id=aid, rollback_token=None,
                            confirmation_kind="consent")
        if step.action_type == ActionType.RETRIGGER_PAYOUT.value and (step.amount or 0) > limit:
            reason = f"amount {step.amount} > auto_limit {limit}"
            aid = _stub_audit(state, step, "NEEDS_CONFIRMATION", ReasonCode.OVER_AUTO_LIMIT, reason,
                              "agent", None, None)
            return Decision(verdict=Verdict.NEEDS_CONFIRMATION, reason_code=ReasonCode.OVER_AUTO_LIMIT,
                            reason=reason, audit_id=aid, rollback_token=None, confirmation_kind="step_up")
        code, actor = ReasonCode.WITHIN_POLICY, "agent"

    token = "rb_" + uuid.uuid4().hex[:12]
    aid = _stub_audit(state, step, "ALLOW", code, "STUB guardrail: allowed", actor, token,
                      confirmation.pending_audit_id if confirmation else None)
    return Decision(verdict=Verdict.ALLOW, reason_code=code, reason="STUB guardrail: allowed",
                    audit_id=aid, rollback_token=token)


# --------------------------------------------------------------------------
# trace (C3 Span) — local jsonl writer until observability/trace.py lands
# --------------------------------------------------------------------------
def emit_span(span: dict) -> None:
    """Append a scrubbed span to traces/{trace_id}.jsonl.

    # STUB: Member 2 owns observability/trace.py. Replace the body with `trace.emit(...)` once the
    # real signature is agreed. The span dict follows CONTRACTS C3 `Span`.
    """
    try:
        path = Path(ROOT) / "traces"
        path.mkdir(exist_ok=True)
        with open(path / f"{span['trace_id']}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(scrub(span), ensure_ascii=False) + "\n")
    except Exception:  # tracing must never break a turn
        pass


# --------------------------------------------------------------------------
# disclosure (COMPLIANCE R1, D1)
# --------------------------------------------------------------------------
_DISCLOSURE_FALLBACK = {  # STUB text; real text lives in compliance/disclosure.py (Member 2)
    "hi-IN": "नमस्ते! मैं चौकस हूँ, Paytm का AI असिस्टेंट। मैं AI हूँ, इंसान नहीं — जब चाहें हमारी टीम के किसी सदस्य से बात कर सकते हैं। आपकी जानकारी सिर्फ़ आपकी समस्या सुलझाने के लिए इस्तेमाल होगी।",
    "en-IN": "Hello! I am Chaukas, Paytm's AI assistant. I am an AI, not a human — you can ask for a team member any time. Your data is used only to resolve your issue.",
}


def get_disclosure(lang: str) -> tuple[str, str]:
    """Returns (text, notice_version)."""
    for name in ("get_disclosure", "disclosure_text"):
        real = _real("chaukas.compliance.disclosure", name)
        if real:
            out = real(lang)
            if isinstance(out, tuple):
                return out
            return out, "v1"
    return _DISCLOSURE_FALLBACK.get(lang, _DISCLOSURE_FALLBACK["en-IN"]), "v1-stub"
