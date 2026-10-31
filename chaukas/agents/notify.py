"""Proactive notification: the first message Chaukas sends when the watcher finds a failed settlement,
and the reply when the merchant declines that payout.

Deterministic template (prompts/proactive_notify.v1.txt), never an LLM: the amount and the settlement id
come from the LEDGER (CLAUDE.md rule 2), and the text works with the network off (replay-safe).

Owner: Member 1 · PROACTIVE_FEATURE_CHANGES.md §4.4
"""
from __future__ import annotations

import re

from chaukas.core.models import ActionType, ConversationState, HandoffReason, Intent, SettlementView
from chaukas.integrations._common import load_config
from chaukas.llm.prompt import load_prompt

TEMPLATE_FILE = "proactive_notify.v1.txt"
_BLOCK = re.compile(r"^\[([A-Za-z-]+)\.([\w.]+)\]\s*$")


def _templates() -> dict[str, dict[str, str]]:
    """{lang: {variant: text}} parsed from the [lang.variant] blocks of the template file.
    Not cached (tests/test_cache_safety.py): a small file, read once per notification."""
    out: dict[str, dict[str, str]] = {}
    lang = key = None
    lines: list[str] = []

    def flush() -> None:
        if lang and key:
            out.setdefault(lang, {})[key] = "\n".join(lines).strip()

    for raw in load_prompt(TEMPLATE_FILE).splitlines():
        if raw.startswith("#"):
            continue
        m = _BLOCK.match(raw)
        if m:
            flush()
            lang, key, lines = m.group(1), m.group(2), []
        else:
            lines.append(raw)
    flush()
    return out


def _lang_templates(lang: str | None) -> dict[str, str]:
    data = _templates()
    return data.get(lang or "") or data["en-IN"]


def variant(state: ConversationState) -> str:
    """Which notification fits what the plan + guardrail did in the proactive turn."""
    pending = state.pending_step
    if pending is not None and pending.action_type == ActionType.RETRIGGER_PAYOUT.value:
        kind = (state.pending_meta or {}).get("kind")
        return "retriggerable" if kind == "consent" else "over_limit"
    reason = state.handoff.reason_code if state.handoff else None
    if reason == HandoffReason.BANK_DETAILS_NOT_UPDATED.value:
        return "bank_details"
    if reason == HandoffReason.KYC_PENDING.value:
        return "kyc"
    return "generic"


def build_device(state: ConversationState, t: dict[str, str]) -> str:
    """Device-upgrade nudge: the numbers are the merchant's own (device advisor), never a model's."""
    pending = state.pending_step
    advice = state.merchant.device_advice if state.merchant else None
    if pending is None or pending.action_type != ActionType.REQUEST_DEVICE_UPGRADE.value or advice is None:
        return t["declined"]  # nothing was parked: say nothing more (the watcher pre-filters, so this is rare)
    return t[f"device.{pending.params['to_device']}"].format(
        txn_count=advice.txn_count_30d, avg_bill=f"{advice.avg_bill_inr:,}", per_day=round(advice.txn_per_active_day))


def build(state: ConversationState, settlement: SettlementView | None, which: str | None = None) -> str:
    """Notification text for this proactive turn (`which` overrides the variant, e.g. 'declined')."""
    t = _lang_templates(state.lang)
    if state.intent == Intent.DEVICE_UPGRADE and which is None:
        return build_device(state, t)
    which = which or variant(state)
    text = t.get(which) or t["generic"]
    cause = settlement.cause if settlement else None
    return text.format(
        amount=f"{settlement.amount:,}" if settlement else "",
        settlement_id=settlement.id if settlement else "",
        cause_text=t.get(f"cause.{cause}", "") if cause else "",
        kyc_link=load_config("mock").get("kyc_link", ""),
    )
