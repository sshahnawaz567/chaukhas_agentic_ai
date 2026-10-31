"""Loads config/policy.yaml and evaluates the 10 ordered checks.
Pure functions; called by chaukas/agents/guardrail.py.

Owner: Member 2 · Contract: CONTRACTS C2

Deterministic: no LLM, no randomness, no network. The only inputs are the step, the state, the policy file
and FRESH reads from the DB (never cached). First failing check wins; a BLOCK can never be undone by a
Confirmation, because checks 1-7 always run before the confirmation is even looked at.
"""
import hmac
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Callable

import yaml
from pydantic import BaseModel, ValidationError

from chaukas.core.models import (
    PARAMS_BY_ACTION, ActionType, Confirmation, ConversationState, PlannedStep, ReasonCode, Verdict,
)
from chaukas.compliance import consent
from chaukas.integrations import insurance
from chaukas.db import ROOT, query_all, query_one
from chaukas.observability.audit import params_masked

_ISO = "%Y-%m-%dT%H:%M:%SZ"
_REQUIRED_KEYS = (
    "auto_limit_inr", "daily_auto_limit_inr", "offer_cooling_off_days", "allow_list", "never_allowed",
    "disabled_actions", "consent_required", "read_only_actions", "money_actions", "pii_fields",
)


def load_policy(path: str | Path | None = None) -> dict:
    """Read config/policy.yaml. Read fresh on every call so a kill-switch edit takes effect at once."""
    p = Path(path) if path else ROOT / "config" / "policy.yaml"
    policy = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    missing = [k for k in _REQUIRED_KEYS if k not in policy]
    if missing:
        raise ValueError(f"policy.yaml is missing keys: {missing}")
    return policy


def load_mock_otp(path: str | Path | None = None) -> str | None:
    """Mock OTP for step-up: config/mock.yaml key 'mock_otp' (Member 1's name; 'otp' is also accepted).
    None = step-up can never pass."""
    p = Path(path) if path else ROOT / "config" / "mock.yaml"
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    otp = data.get("mock_otp", data.get("otp"))
    return str(otp) if otp is not None else None


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    reason_code: ReasonCode
    reason: str
    confirmation_kind: str | None = None     # set on NEEDS_CONFIRMATION: "consent" | "step_up"
    confirms_audit_id: int | None = None     # set on an ALLOW that resolved a pending confirmation
    confirm_actor: str | None = None         # "merchant" | "human" for that ALLOW
    amount: int | None = None                # the amount the decision was made on (for the audit row)


@dataclass
class Ctx:
    step: PlannedStep
    state: ConversationState
    conn: sqlite3.Connection
    policy: dict
    now: datetime
    confirmation: Confirmation | None
    mock_otp: str | None
    amount: int | None = None                # authoritative amount: params.amount once validated
    params: BaseModel | None = None
    confirmed: frozenset = frozenset()       # confirmation kinds that were validated
    confirms_audit_id: int | None = None
    confirm_actor: str | None = None
    confirm_note: str = ""                   # why a supplied confirmation was ignored
    _resolved: bool = False

    @property
    def action(self) -> str:
        return self.step.action_type

    @property
    def merchant_id(self) -> str:
        return self.state.merchant_id

    @property
    def is_money(self) -> bool:
        return self.action in self.policy["money_actions"]


def _block(code: ReasonCode, reason: str) -> Outcome:
    return Outcome(Verdict.BLOCK, code, reason)


def _needs(ctx: Ctx, code: ReasonCode, reason: str, kind: str) -> Outcome:
    if ctx.confirm_note:
        reason += f" (confirmation ignored: {ctx.confirm_note})"
    return Outcome(Verdict.NEEDS_CONFIRMATION, code, reason, confirmation_kind=kind)


# ---------------------------------------------------------------- checks 1-3: is this step even legal?

def check_never_allowed(ctx: Ctx) -> Outcome | None:                                   # 1
    if ctx.action in ctx.policy["never_allowed"]:
        return _block(ReasonCode.NEVER_ALLOWED, f"{ctx.action} is never allowed")
    return None


def check_allow_list(ctx: Ctx) -> Outcome | None:                                      # 2
    if ctx.action not in ctx.policy["allow_list"]:
        return _block(ReasonCode.NOT_IN_ALLOW_LIST, f"{ctx.action} is not in the allow list")
    if ctx.action in ctx.policy["disabled_actions"]:
        return _block(ReasonCode.ACTION_DISABLED, f"{ctx.action} is switched off (kill switch)")
    return None


def check_params(ctx: Ctx) -> Outcome | None:                                          # 3
    def bad(why: str) -> Outcome:
        return _block(ReasonCode.INVALID_PARAMS, why)

    step = ctx.step
    try:
        model = PARAMS_BY_ACTION[ActionType(ctx.action)]
    except (ValueError, KeyError):
        return bad(f"no params schema for {ctx.action}")

    extra = sorted(set(step.params) - set(model.model_fields))
    if extra:
        return bad(f"unexpected params: {extra}")          # e.g. an injected account_no
    if "amount" in step.params and type(step.params["amount"]) is not int:
        return bad("amount must be an int in rupees")      # no float, no "18400" string, no bool
    try:
        params = model.model_validate(step.params)
    except ValidationError as e:                           # only field names, never the values (may be PII)
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()})
        return bad(f"invalid params: {fields}")
    ctx.params = params

    amount = getattr(params, "amount", None)
    if amount is not None:
        if step.amount is not None and step.amount != amount:
            return bad(f"step.amount {step.amount} != params.amount {amount}")
        ctx.amount = amount

    if getattr(params, "merchant_id", None) not in (None, ctx.merchant_id):
        return bad("merchant_id does not match the session merchant")

    settlement_id = getattr(params, "settlement_id", None)
    if settlement_id:
        row = query_one(ctx.conn, "SELECT merchant_id FROM settlements WHERE id = ?", (settlement_id,))
        if row and row["merchant_id"] != ctx.merchant_id:
            return bad("settlement belongs to another merchant")

    ticket_id = getattr(params, "ticket_id", None)
    if ticket_id:
        row = query_one(ctx.conn, "SELECT merchant_id FROM tickets WHERE id = ?", (ticket_id,))
        if row is None or row["merchant_id"] != ctx.merchant_id:
            return bad("ticket not found for this merchant")
    return None


# ---------------------------------------------------------------- checks 4-7: fresh facts from the DB

def idempotency_key(ctx: Ctx) -> str:
    return f"{ctx.state.session_id}:{ctx.step.step_no}"


def check_idempotency(ctx: Ctx) -> Outcome | None:                                     # 4
    if query_one(ctx.conn, "SELECT 1 FROM executions WHERE idempotency_key = ?", (idempotency_key(ctx),)):
        return _block(ReasonCode.DUPLICATE_ACTION, f"step {idempotency_key(ctx)} was already executed")
    return None


def _settlement(ctx: Ctx):
    return query_one(ctx.conn, "SELECT * FROM settlements WHERE id = ?", (ctx.params.settlement_id,))


def check_ledger(ctx: Ctx) -> Outcome | None:                                          # 5
    if ctx.action != "retrigger_payout":
        return None
    row = _settlement(ctx)
    if row is None or row["merchant_id"] != ctx.merchant_id:
        return _block(ReasonCode.LEDGER_MISMATCH, f"settlement {ctx.params.settlement_id} not found for this merchant")
    if ctx.amount != row["amount"]:
        return _block(ReasonCode.LEDGER_MISMATCH, f"amount {ctx.amount} != ledger amount {row['amount']}")
    return None


def check_retriggerable(ctx: Ctx) -> Outcome | None:                                   # 6
    if ctx.action != "retrigger_payout":
        return None
    row = _settlement(ctx)

    def no(why: str) -> Outcome:
        return _block(ReasonCode.NOT_RETRIGGERABLE, f"{row['id']}: {why}")

    if row["status"] != "failed":
        return no(f"status is {row['status']}, only a failed settlement can be retriggered")
    if row["cause"] == "BANK_DOWN":
        return None
    if row["cause"] == "IFSC_MISMATCH":
        fixed_at = query_one(ctx.conn, "SELECT bank_details_updated_at FROM merchants WHERE merchant_id = ?",
                             (ctx.merchant_id,))["bank_details_updated_at"]
        if fixed_at and fixed_at > row["settlement_date"]:   # ISO strings compare in time order
            return None
        return no("IFSC_MISMATCH and bank details not updated since the failure")
    return no(f"cause {row['cause']} is never retriggerable")


def _open_issue(ctx: Ctx) -> str | None:
    """A failed settlement, or a pending one nobody has actioned yet. 'retriggered' counts as actioned."""
    ticket_done = query_one(
        ctx.conn,
        "SELECT 1 FROM executions WHERE session_id = ? AND action_type IN ('raise_ticket','update_ticket') "
        "AND status IN ('pending','success')", (ctx.state.session_id,)) is not None
    for s in query_all(ctx.conn, "SELECT id, status FROM settlements WHERE merchant_id = ? "
                       "AND status IN ('failed','pending')", (ctx.merchant_id,)):
        if s["status"] == "failed":
            return f"settlement {s['id']} is still failed"
        has_ticket = query_one(ctx.conn, "SELECT 1 FROM tickets WHERE settlement_id = ? AND status IN "
                               "('open','in_progress')", (s["id"],)) is not None
        if not (ticket_done or has_ticket):
            return f"settlement {s['id']} is pending and not actioned"
    return None


def _insurance_gating(ctx: Ctx) -> Outcome | None:
    """check 7 for offer_insurance: the same sales rules as a loan offer (issue first, KYC, no open handoff,
    cooling-off, consent not withdrawn) plus: the product must be the one the rules recommend for this merchant
    RIGHT NOW, read fresh from the DB by the same function the agent used. An injected or stale product id is a BLOCK."""
    mid = ctx.merchant_id
    if consent.is_withdrawn(ctx.conn, mid, "insurance_offer"):            # DPDP s.6: next turn respects it
        return _block(ReasonCode.CONSENT_WITHDRAWN, "the merchant withdrew consent for insurance offers")
    wanted = getattr(ctx.params, "product_id", None)
    fit = insurance.recommend(ctx.conn, mid)
    if fit is None or fit["product_id"] != wanted:
        return _block(ReasonCode.OFFER_NOT_ELIGIBLE, "this insurance is not recommended for this merchant")
    if insurance.has_open_lead(ctx.conn, mid, wanted):
        return _block(ReasonCode.OFFER_NOT_ELIGIBLE, "the merchant already asked for this insurance")

    issue = _open_issue(ctx)
    if issue:
        return _block(ReasonCode.ISSUE_UNRESOLVED, issue)
    kyc = query_one(ctx.conn, "SELECT kyc_status FROM merchants WHERE merchant_id = ?", (mid,))["kyc_status"]
    if kyc != "verified":
        return _block(ReasonCode.ISSUE_UNRESOLVED, f"kyc_status is {kyc}")
    if query_one(ctx.conn, "SELECT 1 FROM handoffs WHERE merchant_id = ? AND status IN ('open','claimed')", (mid,)):
        return _block(ReasonCode.ISSUE_UNRESOLVED, "an open handoff exists for this merchant")
    days = ctx.policy["offer_cooling_off_days"]
    if insurance.declined_recently(ctx.conn, mid, ctx.now, days):
        return _block(ReasonCode.OFFER_COOLING_OFF, f"an insurance offer was declined within the last {days} days")
    return None


def check_offer_gating(ctx: Ctx) -> Outcome | None:                                    # 7
    if ctx.action == "offer_insurance":
        return _insurance_gating(ctx)
    if ctx.action != "create_offer":
        return None
    if consent.is_withdrawn(ctx.conn, ctx.merchant_id, "loan_offer"):     # DPDP s.6: next turn respects it
        return _block(ReasonCode.CONSENT_WITHDRAWN, "the merchant withdrew consent for loan offers")
    product = getattr(ctx.params, "product", "term_loan")
    if product in (ctx.policy.get("disabled_offer_products") or []):   # per-product kill switch (FREE-AI R5)
        return _block(ReasonCode.ACTION_DISABLED, f"{product} offers are switched off (kill switch)")
    merchant = ctx.state.merchant
    # each product is capped by the lender's answer FOR THAT PRODUCT; a term-loan answer never caps a credit line
    lender = (merchant.credit_line if product == "credit_line" else merchant.eligibility) if merchant else None
    if lender is None or not lender.eligible or lender.product != product:   # no lender answer = fail closed
        return _block(ReasonCode.OFFER_NOT_ELIGIBLE, f"lender did not confirm eligibility for {product}")
    if ctx.amount > lender.max_amount:
        return _block(ReasonCode.OFFER_NOT_ELIGIBLE, f"amount {ctx.amount} > lender max_amount {lender.max_amount}")
    if product == "credit_line":                        # total exposure: no credit line on top of a fresh loan
        days = int(ctx.policy.get("credit_line_after_loan_days", 30))
        since = (ctx.now - timedelta(days=days)).strftime(_ISO)
        if query_one(ctx.conn, "SELECT 1 FROM offers WHERE merchant_id = ? AND status = 'accepted' "
                     "AND consent_at >= ?", (ctx.merchant_id, since)):
            return _block(ReasonCode.OFFER_NOT_ELIGIBLE, f"a loan was accepted within the last {days} days")

    issue = _open_issue(ctx)
    if issue:
        return _block(ReasonCode.ISSUE_UNRESOLVED, issue)
    kyc = query_one(ctx.conn, "SELECT kyc_status FROM merchants WHERE merchant_id = ?", (ctx.merchant_id,))["kyc_status"]
    if kyc != "verified":
        return _block(ReasonCode.ISSUE_UNRESOLVED, f"kyc_status is {kyc}")
    if query_one(ctx.conn, "SELECT 1 FROM handoffs WHERE merchant_id = ? AND status IN ('open','claimed')",
                 (ctx.merchant_id,)):
        return _block(ReasonCode.ISSUE_UNRESOLVED, "an open handoff exists for this merchant")

    return _sales_cooling_off(ctx)


def _sales_cooling_off(ctx: Ctx) -> Outcome | None:
    """ONE cooling-off for every sales offer (team decision 31 Oct): a declined loan, credit line or device offer
    blocks every sales offer for offer_cooling_off_days."""
    days = ctx.policy["offer_cooling_off_days"]
    cutoff = (ctx.now - timedelta(days=days)).strftime(_ISO)
    for table in ("offers", "device_offers"):
        if query_one(ctx.conn, f"SELECT 1 FROM {table} WHERE merchant_id = ? AND status = 'declined' "
                     "AND declined_at >= ?", (ctx.merchant_id, cutoff)):
            return _block(ReasonCode.OFFER_COOLING_OFF, f"an offer was declined within the last {days} days")
    return None


def check_device_gating(ctx: Ctx) -> Outcome | None:                                  # 7b
    """request_device_upgrade (DEVICE_UPGRADE_PLAN.md §4): the advisor's answer, support first, cooling-off."""
    if ctx.action != "request_device_upgrade":
        return None
    if consent.is_withdrawn(ctx.conn, ctx.merchant_id, "device_offer"):     # DPDP s.6
        return _block(ReasonCode.CONSENT_WITHDRAWN, "the merchant withdrew consent for device offers")
    p = ctx.params
    m = query_one(ctx.conn, "SELECT device, kyc_status FROM merchants WHERE merchant_id = ?", (ctx.merchant_id,))
    if m is None or m["device"] != p.from_device:
        return _block(ReasonCode.INVALID_PARAMS, f"from_device {p.from_device} is not the merchant's device")
    advice = ctx.state.merchant.device_advice if ctx.state.merchant else None
    if (advice is None or not advice.recommended or advice.from_device != p.from_device
            or advice.to_device != p.to_device):                            # no advisor answer = fail closed
        return _block(ReasonCode.OFFER_NOT_ELIGIBLE, f"the device advisor does not recommend {p.to_device}")
    if query_one(ctx.conn, "SELECT 1 FROM settlements WHERE merchant_id = ? AND status IN ('failed','pending')",
                 (ctx.merchant_id,)):
        return _block(ReasonCode.ISSUE_UNRESOLVED, "a settlement is still failed or pending")
    if query_one(ctx.conn, "SELECT 1 FROM tickets WHERE merchant_id = ? AND status IN ('open','in_progress')",
                 (ctx.merchant_id,)):
        return _block(ReasonCode.ISSUE_UNRESOLVED, "an open support ticket exists for this merchant")
    if m["kyc_status"] != "verified":
        return _block(ReasonCode.ISSUE_UNRESOLVED, f"kyc_status is {m['kyc_status']}")
    if query_one(ctx.conn, "SELECT 1 FROM handoffs WHERE merchant_id = ? AND status IN ('open','claimed')",
                 (ctx.merchant_id,)):
        return _block(ReasonCode.ISSUE_UNRESOLVED, "an open handoff exists for this merchant")
    if query_one(ctx.conn, "SELECT 1 FROM device_offers WHERE merchant_id = ? AND to_device = ? AND status = 'accepted'",
                 (ctx.merchant_id, p.to_device)):
        return _block(ReasonCode.OFFER_NOT_ELIGIBLE, f"{p.to_device} was already requested")
    return _sales_cooling_off(ctx)


# ---------------------------------------------------------------- confirmation (can satisfy 8-10 only)

def _resolve_confirmation(ctx: Ctx) -> None:
    """Validate ctx.confirmation once. On success fills ctx.confirmed; otherwise ctx.confirm_note says why."""
    if ctx._resolved or ctx.confirmation is None:
        return
    ctx._resolved = True
    c = ctx.confirmation
    row = query_one(ctx.conn, "SELECT * FROM audit_log WHERE id = ?", (c.pending_audit_id,))
    why = None
    if row is None:
        why = "pending audit row not found"
    elif row["guardrail_decision"] != "NEEDS_CONFIRMATION":
        why = "audit row is not a pending confirmation"
    elif row["merchant_id"] != ctx.merchant_id or row["session_id"] != ctx.state.session_id:
        why = "pending row belongs to another session"
    elif (row["action_type"] != ctx.action or row["amount"] != ctx.amount
          or row["params_masked"] != params_masked(ctx.step.params)):
        why = "step differs from the one that was pending"      # bait-and-switch
    elif query_one(ctx.conn, "SELECT 1 FROM audit_log WHERE confirms_audit_id = ? AND guardrail_decision = 'ALLOW'",
                   (row["id"],)):
        why = "already used"
    else:
        expected = "step_up" if row["reason_code"] in ("OVER_AUTO_LIMIT", "OVER_DAILY_LIMIT") else "consent"
        if c.actor == "human":
            if not c.actor_id:
                why = "human approval needs actor_id"
        elif c.kind != expected:
            why = f"this step needs {expected}, got {c.kind}"
        elif expected == "step_up" and not (
                ctx.mock_otp and c.otp and hmac.compare_digest(str(c.otp), ctx.mock_otp)):
            why = "invalid OTP"
    if why:
        ctx.confirm_note = why
        return
    ctx.confirmed = frozenset({"step_up", "consent"}) if c.actor == "human" else frozenset({c.kind})
    ctx.confirms_audit_id = row["id"]
    ctx.confirm_actor = c.actor


def _is_confirmed(ctx: Ctx, kind: str) -> bool:
    _resolve_confirmation(ctx)
    return kind in ctx.confirmed


# ---------------------------------------------------------------- checks 8-10: ask the human

def check_auto_limit(ctx: Ctx) -> Outcome | None:                                      # 8
    limit = ctx.policy["auto_limit_inr"]
    if ctx.is_money and ctx.amount > limit and not _is_confirmed(ctx, "step_up"):
        return _needs(ctx, ReasonCode.OVER_AUTO_LIMIT, f"amount {ctx.amount} > auto_limit {limit}", "step_up")
    return None


def todays_total(ctx: Ctx) -> int:
    marks = ",".join("?" for _ in ctx.policy["money_actions"])
    row = query_one(
        ctx.conn,
        f"SELECT COALESCE(SUM(amount), 0) AS total FROM executions WHERE merchant_id = ? "
        f"AND action_type IN ({marks}) AND status IN ('pending','success') AND substr(created_at, 1, 10) = ?",
        (ctx.merchant_id, *ctx.policy["money_actions"], ctx.now.strftime("%Y-%m-%d")))
    return row["total"]


def check_daily_limit(ctx: Ctx) -> Outcome | None:                                     # 9
    if not ctx.is_money:
        return None
    limit, total = ctx.policy["daily_auto_limit_inr"], todays_total(ctx)
    if total + ctx.amount > limit and not _is_confirmed(ctx, "step_up"):
        return _needs(ctx, ReasonCode.OVER_DAILY_LIMIT,
                      f"today_total {total} + amount {ctx.amount} > daily_auto_limit {limit}", "step_up")
    return None


def session_trigger_source(ctx: Ctx) -> str:
    """'merchant' | 'proactive', read FRESH from sessions.trigger_source. Never from state or the request:
    a bug (or tampered state) must not be able to turn a proactive session into a reactive one.
    No sessions row (unit tests, /api/redteam/check) = no proactive evidence = 'merchant'; the event watcher
    always creates the row, so a real proactive session is never missing."""
    row = query_one(ctx.conn, "SELECT trigger_source FROM sessions WHERE session_id = ?", (ctx.state.session_id,))
    return row["trigger_source"] if row else "merchant"


def check_consent(ctx: Ctx) -> Outcome | None:                                         # 10
    required = ctx.policy["consent_required"]
    needs = ctx.action in required or (not ctx.step.reversible and "any_irreversible" in required)
    # Proactive: Chaukas started this, the merchant asked for nothing -> money never moves without a yes.
    # Default (key absent) = every money action + create_offer, so a stripped policy fails safe.
    proactive = ctx.policy.get("proactive_consent_required", [*ctx.policy["money_actions"], "create_offer"])
    if ctx.action in proactive and session_trigger_source(ctx) == "proactive":
        needs = True
    if needs and not _is_confirmed(ctx, "consent"):
        return _needs(ctx, ReasonCode.CONSENT_REQUIRED, f"{ctx.action} needs the merchant's consent", "consent")
    return None


LEGALITY: list[Callable[[Ctx], Outcome | None]] = [check_never_allowed, check_allow_list, check_params]
FACTS: list[Callable[[Ctx], Outcome | None]] = [
    check_idempotency, check_ledger, check_retriggerable, check_offer_gating, check_device_gating,
]
CONFIRMATIONS: list[Callable[[Ctx], Outcome | None]] = [check_auto_limit, check_daily_limit, check_consent]


def _run(ctx: Ctx, checks: list[Callable[[Ctx], Outcome | None]]) -> Outcome | None:
    for check in checks:
        outcome = check(ctx)
        if outcome is not None:
            return replace(outcome, amount=ctx.amount)
    return None


def evaluate(
    step: PlannedStep, state: ConversationState, conn: sqlite3.Connection, policy: dict,
    confirmation: Confirmation | None = None, now: datetime | None = None, mock_otp: str | None = None,
) -> Outcome:
    """Run the checks in order and return the first failure, or the ALLOW outcome."""
    ctx = Ctx(step=step, state=state, conn=conn, policy=policy, now=now or datetime.now(timezone.utc),
              confirmation=confirmation, mock_otp=mock_otp, amount=step.amount)

    out = _run(ctx, LEGALITY)
    if out:
        return out
    if ctx.action in policy["read_only_actions"]:        # read-only: checks 1-3 only
        return Outcome(Verdict.ALLOW, ReasonCode.WITHIN_POLICY, f"{ctx.action} is read-only", amount=ctx.amount)
    out = _run(ctx, FACTS) or _run(ctx, CONFIRMATIONS)
    if out:
        return out

    if ctx.confirms_audit_id is not None:
        code = ReasonCode.APPROVED_BY_HUMAN if ctx.confirm_actor == "human" else ReasonCode.CONFIRMED_BY_MERCHANT
        return Outcome(Verdict.ALLOW, code, f"{ctx.action} confirmed by {ctx.confirm_actor}",
                       confirms_audit_id=ctx.confirms_audit_id, confirm_actor=ctx.confirm_actor, amount=ctx.amount)
    detail = f"amount {ctx.amount} <= auto_limit {policy['auto_limit_inr']}" if ctx.is_money else "all checks passed"
    return Outcome(Verdict.ALLOW, ReasonCode.WITHIN_POLICY, f"{ctx.action}: {detail}", amount=ctx.amount)
