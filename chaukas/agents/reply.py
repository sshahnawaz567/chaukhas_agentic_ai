"""Reply generation in the merchant's language. LLM sees reason codes and
masked facts only — never raw cashflow numbers.

If the LLM is unavailable (and no recording exists) a deterministic template from
config/fallback_replies.yaml is used, so the demo never goes silent.

Owner: Member 1 · Contract: CONTRACTS C1
"""
from __future__ import annotations

import re
from typing import Any

import yaml

from chaukas.agents.schemas import ReplyOutput
from chaukas.core.models import ActionType, ConversationState, Intent, ReasonCode, Verdict
from chaukas.db import ROOT
from chaukas.integrations._common import load_config
from chaukas.integrations.lending import build_kfs
from chaukas.llm.client import LLMResult, LLMUnavailable
from chaukas.llm.prompt import LLMOutputError, esc, run_validated, to_xml

# What a refusal means in plain words (the LLM must not see/say internal reason codes).
_REFUSAL_PLAIN = {
    ReasonCode.OVER_AUTO_LIMIT: "amount is large; the team must verify it before sending",
    ReasonCode.OVER_DAILY_LIMIT: "today's total is large; the team must verify it before sending",
    ReasonCode.OFFER_NOT_ELIGIBLE: "merchant is not eligible for a loan right now",
    ReasonCode.OFFER_COOLING_OFF: "a loan offer is not appropriate right now",
    ReasonCode.ISSUE_UNRESOLVED: "a loan offer is not appropriate until the open issue is resolved",
    ReasonCode.NOT_RETRIGGERABLE: "the payout cannot be re-sent in the current state",
    ReasonCode.LEDGER_MISMATCH: "the amount did not match the records",
}

_CAUSE_PLAIN = {
    "IFSC_MISMATCH": "bank details (IFSC) were wrong",
    "BANK_DOWN": "the bank was temporarily down",
    "KYC_PENDING": "KYC is not complete",
}


def _templates(lang: str) -> dict[str, str]:
    data = yaml.safe_load((ROOT / "config" / "fallback_replies.yaml").read_text(encoding="utf-8"))
    return data.get(lang) or data["en-IN"]


def _refs(state: ConversationState) -> dict[str, str | None]:
    """action_type -> ref of the (first) successful write in this turn."""
    out: dict[str, str | None] = {}
    for r in state.completed:
        if r.status == "success" and r.ref_id and r.action_type not in out:
            out[r.action_type] = r.ref_id
    return out


def build_facts(state: ConversationState) -> dict[str, Any]:
    """Everything the reply may say. Amounts come from the ledger / lender, ids from action results."""
    mcfg = load_config("mock")
    facts: dict[str, Any] = {"lang": state.lang or "hi-IN", "intent": state.intent.value if state.intent else "unknown"}
    refs = _refs(state)
    tags = list(state.outcome_tags)
    facts["outcome_tags"] = tags or None

    ctx = state.merchant
    if state.intent == Intent.SETTLEMENT_DELAY and ctx is not None:
        relevant = [s for s in ctx.settlements if s.status in ("failed", "pending", "retriggered")][:3]
        facts["settlements"] = [
            {"id": s.id, "amount": s.amount, "status": s.status, "why": _CAUSE_PLAIN.get(s.cause or "", None)}
            for s in relevant
        ] or None
        if not relevant:
            facts["all_settlements_ok"] = True
        if any(s.status == "pending" for s in relevant):
            facts["eta_hours"] = mcfg.get("bank_down_eta_hours", 24)
        if any(s.cause == "KYC_PENDING" for s in relevant):
            facts["kyc_link"] = mcfg.get("kyc_link")

    done = []
    for r in state.completed:
        if r.status != "success" or r.action_type in (ActionType.VERIFY_LEDGER.value, ActionType.CHECK_ELIGIBILITY.value):
            continue
        step = next((p for p in state.plan if p.step_no == r.step_no), None)
        label = {"retrigger_payout": "payout_resent", "raise_ticket": "ticket_created",
                 "update_ticket": "ticket_updated", "create_offer": "offer_accepted"}.get(r.action_type, r.action_type)
        done.append({"what": label, "ref": r.ref_id, "amount": step.amount if step else None})
    facts["done"] = done or None

    failed = [r for r in state.completed if r.status in ("failed", "rolled_back")]
    if failed:
        facts["action_failed"] = True

    facts["refused"] = [{"what": x.action_type, "why": _REFUSAL_PLAIN.get(x.reason_code, "not allowed")}
                        for x in state.refused] or None

    if state.pending_step and state.pending_step.action_type == ActionType.CREATE_OFFER.value:
        p = state.pending_step.params
        kfs = build_kfs(p["merchant_id"], p["amount"])
        facts["offer_kfs"] = {"amount": p["amount"], **kfs.model_dump()}
    if state.handoff is not None:
        facts["handoff"] = True
    facts["outcome"] = _outcome(state, facts, done) or None
    return facts


def _outcome(state: ConversationState, facts: dict, done: list[dict]) -> list[str]:
    """Plain statements of the COMPLETE truth of this turn. The reply may say these and nothing more."""
    out: list[str] = []
    paid = any(d["what"] == "payout_resent" for d in done)
    ctx = state.merchant
    if state.intent == Intent.REFUND_REQUEST:
        out.append("This assistant cannot process refunds; the request is passed to the human team.")
    elif state.intent == Intent.HUMAN_REQUEST:
        out.append("The merchant is being connected to a human team member.")
    elif state.intent == Intent.UNKNOWN:
        out.append("The message was not understood; it is passed to the human team.")
    if facts.get("all_settlements_ok"):
        out.append("All settlements are successful. Nothing is pending. No payout or other action was needed.")
    if any(s["status"] == "pending" for s in facts.get("settlements") or []):
        out.append("The payout is pending at the bank. NO payout was re-sent. The bank is processing it.")
    if facts.get("kyc_link"):
        out.append("KYC is incomplete, which holds the payout. NO payout was re-sent. The merchant must complete KYC.")
    if state.handoff and state.handoff.reason_code == "BANK_DETAILS_NOT_UPDATED":
        out.append("Bank details are not updated since the failure. NO payout was re-sent. The team will contact the merchant.")
    if {r.reason_code for r in state.refused} & {ReasonCode.OVER_AUTO_LIMIT, ReasonCode.OVER_DAILY_LIMIT}             or "step_up_required" in state.outcome_tags:
        out.append("The payout was NOT sent yet. The amount needs verification by the human team first.")
    if ctx is not None and state.intent == Intent.SETTLEMENT_DELAY and not paid and not out:
        out.append("No payout was re-sent in this turn.")
    if paid:
        out.append("The failed payout was re-sent.")
    if "loan_not_eligible" in state.outcome_tags:
        out.append("The merchant is not eligible for a loan right now.")
    if "offer_declined" in state.outcome_tags:
        out.append("The merchant declined the loan offer; nothing was sent.")
    if "nothing_pending" in state.outcome_tags:
        out.append("There is no pending request to confirm.")
    return out


# Phrases that claim a payout was / will be sent. Only allowed when a payout really was re-sent.
_PAYOUT_CLAIM = re.compile(
    r"(भेज\s*दिया|भेजा\s*गया|भेज\s*दी|भेजा\s*जाएगा|भेज\s*देंगे|दोबारा\s*भेज|फिर\s*से\s*भेज|"
    r"re-?sent|re-?sending|re-?triggered|has\s+been\s+sent|have\s+sent|will\s+be\s+(?:re-?)?sent|sent\s+again)", re.I)
_IDS = re.compile(r"\b(?:TKT|PAY|OFF|SET|HO)-\d+(?:-\d+)?\b")


def _grounded(reply: str, state: ConversationState, facts: dict) -> bool:
    """Deterministic check on the LLM's reply: no invented ids, no claim of a payout that did not happen."""
    known = {d["ref"] for d in (facts.get("done") or []) if d.get("ref")}
    known |= {s["id"] for s in facts.get("settlements") or []}
    known |= {t["id"] for t in (state.merchant.open_tickets if state.merchant else [])}
    if any(i not in known for i in _IDS.findall(reply)):
        return False
    paid = any(d["what"] == "payout_resent" for d in (facts.get("done") or []))
    if not paid and any(not _negated(reply, m) for m in _PAYOUT_CLAIM.finditer(reply)):
        return False
    return True


_NEGATION = re.compile(r"(नहीं|नही|\bnot\b|n't|\bnever\b|\bno\b|\bnahi\b|\bnahin\b)", re.I)


def _negated(text: str, m: re.Match) -> bool:
    """'payout दोबारा नहीं भेजा गया' states the opposite of a claim: look for a negation next to the verb."""
    return bool(_NEGATION.search(text[max(0, m.start() - 30):m.start()]) or _NEGATION.search(text[m.end():m.end() + 12]))


def _signature(state: ConversationState, facts: dict) -> str:
    """Stable (id-free) description of the outcome, for replay keys."""
    done = ",".join(d["what"] for d in (facts.get("done") or []))
    refused = ",".join(x.reason_code.value for x in state.refused)
    return f"{facts['intent']}|{','.join(state.outcome_tags)}|{done}|{refused}|{bool(state.handoff)}|{'offer_kfs' in facts}"


def fallback_reply(state: ConversationState, facts: dict) -> str:
    t = _templates(facts["lang"])
    parts: list[str] = []
    tags = set(state.outcome_tags)
    done = {d["what"]: d for d in (facts.get("done") or [])}
    refused_codes = {x.reason_code for x in state.refused}

    if "nothing_pending" in tags:
        return t["nothing_pending"]
    if "offer_declined" in tags:
        return t["offer_declined"]
    if state.intent == Intent.HUMAN_REQUEST:
        return t["human"]
    if state.intent == Intent.REFUND_REQUEST:
        return t["refund"]
    if state.intent == Intent.UNKNOWN:
        return t["unclear"]

    if facts.get("all_settlements_ok"):
        parts.append(t["all_good"])
    for s in facts.get("settlements") or []:
        if s["status"] == "pending":
            parts.append(t["pending_wait"].format(amount=f"{s['amount']:,}", eta_hours=facts.get("eta_hours", 24)))
    if "payout_resent" in done:
        parts.append(t["retriggered"].format(amount=f"{done['payout_resent']['amount']:,}"))
    if "ticket_updated" in done:
        parts.append(t["ticket_updated"].format(ticket_id=done["ticket_updated"]["ref"]))
    elif "ticket_created" in done:
        key = "device_ticket" if state.intent == Intent.DEVICE_ISSUE else "ticket_raised"
        parts.append(t[key].format(ticket_id=done["ticket_created"]["ref"]))
    if facts.get("kyc_link"):
        parts.append(t["kyc"].format(kyc_link=facts["kyc_link"]))
    if state.handoff and state.handoff.reason_code == "BANK_DETAILS_NOT_UPDATED":
        parts.append(t["bank_not_updated"])
    if refused_codes & {ReasonCode.OVER_AUTO_LIMIT, ReasonCode.OVER_DAILY_LIMIT} or "step_up_required" in tags:
        parts.append(t["over_limit"])
    if facts.get("action_failed"):
        parts.append(t["action_failed"])
    if "offer_accepted" in done:
        amount = next((p.amount for p in state.plan if p.action_type == "create_offer"), None)
        parts.append(t["offer_accepted"].format(offer_id=done["offer_accepted"]["ref"], amount=f"{amount:,}" if amount else ""))
    if "offer_kfs" in facts:
        k = facts["offer_kfs"]
        parts.append(t["offer"].format(amount=f"{k['amount']:,}", lender_name=k["lender_name"], apr_pct=k["apr_pct"],
                                       fee=f"{k['processing_fee_inr']:,}", tenure=k["tenure_months"],
                                       total=f"{k['total_repayable_inr']:,}", grievance=k["grievance_contact"]))
    if ReasonCode.OFFER_NOT_ELIGIBLE in refused_codes:
        parts.append(t["offer_not_eligible"])
    elif refused_codes & {ReasonCode.OFFER_COOLING_OFF, ReasonCode.ISSUE_UNRESOLVED}:
        parts.append(t["offer_later"])
    if "loan_not_eligible" in tags:
        parts.append(t["offer_not_eligible"])
    if state.handoff and not parts:
        parts.append(t["handoff"])
    return " ".join(parts) or t["handoff"]


def generate(state: ConversationState) -> tuple[str, LLMResult | None, str]:
    """Returns (reply_text, llm_result_or_None, source) with source in {"llm", "template"}."""
    facts = build_facts(state)
    context = to_xml("reply_context", facts)
    variables = {"context": context, "user_question": esc(state.message_masked)}
    replay_key = f"reply|{state.merchant_id}|{state.message_masked}|{_signature(state, facts)}"
    try:
        out, llm = run_validated("reply", "reply.v1.txt", variables, ReplyOutput, replay_key=replay_key)
        text = out.reply_result.reply.strip()
        if llm.source == "replay":  # recorded text may carry stale ids: prefer the exact template
            return fallback_reply(state, facts), llm, "template"
        if not _grounded(text, state, facts):  # the model claimed something that did not happen
            return fallback_reply(state, facts), llm, "template(ungrounded)"
        return text, llm, "llm"
    except (LLMUnavailable, LLMOutputError):
        return fallback_reply(state, facts), None, "template"
