"""[MOCK] SIMULATED lender: check_eligibility -> {eligible, max_amount, reason_codes}
(from cashflow_features + config/lender_sim.yaml), create_offer, withdraw_offer.

In production the regulated lender decides this; Chaukas only consumes the result.
Owner: Member 1 · Contract: CONTRACTS C3 / design B4.1
"""
from __future__ import annotations

import json

from chaukas import db
from chaukas.core.models import KFS, LenderDecision, Offer, RollbackResult
from chaukas.integrations._common import deterministic_id, execution_by_token, load_config, stored_ref


def check_eligibility(merchant_id: str) -> LenderDecision:
    cfg = load_config("lender_sim")
    rules, cap_cfg = cfg["eligibility"], cfg["max_amount"]
    conn = db.connect()
    try:
        f = conn.execute("SELECT * FROM cashflow_features WHERE merchant_id=?", (merchant_id,)).fetchone()
    finally:
        conn.close()
    if not f:
        return LenderDecision(eligible=False, max_amount=0, reason_codes=["NO_CASHFLOW_DATA"])

    checks = [
        ("AVG_BALANCE_OK", "AVG_BALANCE_LOW", f["avg_balance"] >= rules["min_avg_balance"]),
        ("ACCOUNT_AGE_OK", "ACCOUNT_TOO_NEW", f["account_age_months"] >= rules["min_account_age_months"]),
        ("INFLOW_STEADY", "INFLOW_VOLATILE", f["inflow_cv"] <= rules["max_inflow_cv"]),
        ("ACTIVE_DAYS_OK", "ACTIVE_DAYS_LOW", f["active_days_30d"] >= rules["min_active_days_30d"]),
    ]
    codes = [ok if passed else bad for ok, bad, passed in checks]
    eligible = all(p for _, _, p in checks)
    max_amount = 0
    if eligible:
        step = cap_cfg["round_to"]
        raw = int(f["inflow_30d"] * cap_cfg["inflow_fraction"])
        max_amount = min(raw // step * step, cap_cfg["max_loan_cap_inr"])
    return LenderDecision(eligible=eligible and max_amount > 0, max_amount=max_amount, reason_codes=codes)


def build_kfs(merchant_id: str, amount: int) -> KFS:
    """Key Fact Statement (RBI Digital Lending). MOCK values from config/lender_sim.yaml."""
    cfg = load_config("lender_sim")
    k = cfg["kfs"]
    fee = round(amount * k["processing_fee_pct"] / 100)
    interest = round(amount * k["apr_pct"] / 100 * k["tenure_months"] / 12)
    return KFS(lender_name=cfg["lender_name"], apr_pct=k["apr_pct"], processing_fee_inr=fee,
               tenure_months=k["tenure_months"], total_repayable_inr=amount + interest + fee,
               grievance_contact=k["grievance_contact"])


def create_offer(merchant_id: str, amount: int, consent: bool, kfs: KFS, session_id: str,
                 idempotency_key: str, kfs_shown_at: str | None = None,
                 trace_id: str | None = None) -> Offer:
    """Record an ACCEPTED offer. Only valid after the KFS was shown and the merchant consented.

    `kfs_shown_at` (additive kwarg) is the time the KFS was presented, captured by the orchestrator;
    the DB CHECK rejects 'accepted' without it.
    """
    if not consent:
        raise ValueError("create_offer requires merchant consent")
    if not kfs_shown_at:
        raise ValueError("KFS must be shown before consent (kfs_shown_at missing)")
    conn = db.connect()
    try:
        prior = stored_ref(conn, idempotency_key)
        if prior:
            return Offer(offer_id=prior, status="accepted")
        offer_id = deterministic_id(conn, "OFF", idempotency_key, "offers")
        now = db.now_iso()
        conn.execute(
            """INSERT INTO offers (id, merchant_id, session_id, trace_id, amount, consent, consent_at,
                   lender_name, kfs_json, kfs_shown_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (offer_id, merchant_id, session_id, trace_id, amount, 1, now, kfs.lender_name,
             json.dumps(kfs.model_dump(), ensure_ascii=False), kfs_shown_at, "accepted"),
        )
        conn.commit()
        return Offer(offer_id=offer_id, status="accepted")
    finally:
        conn.close()


def record_declined_offer(merchant_id: str, amount: int, session_id: str, trace_id: str | None,
                          kfs_shown_at: str | None) -> str:
    """Merchant said no to a presented offer: store it as 'declined' so the cooling-off window
    (guardrail OFFER_COOLING_OFF) starts. Not a guarded action: nothing is granted or moved."""
    conn = db.connect()
    try:
        offer_id = deterministic_id(conn, "OFF", f"declined:{session_id}:{amount}", "offers")
        now = db.now_iso()
        kfs = build_kfs(merchant_id, amount)
        conn.execute(
            """INSERT INTO offers (id, merchant_id, session_id, trace_id, amount, consent, declined_at,
                   lender_name, kfs_json, kfs_shown_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (offer_id, merchant_id, session_id, trace_id, amount, 0, now, kfs.lender_name,
             json.dumps(kfs.model_dump(), ensure_ascii=False), kfs_shown_at, "declined"),
        )
        conn.commit()
        return offer_id
    finally:
        conn.close()


def withdraw_offer(rollback_token: str) -> RollbackResult:
    conn = db.connect()
    try:
        ex = execution_by_token(conn, rollback_token)
        if not ex or not ex["result_ref"]:
            return RollbackResult(ok=True, detail="nothing to roll back")
        conn.execute("UPDATE offers SET status='expired' WHERE id=?", (ex["result_ref"],))
        conn.commit()
        return RollbackResult(ok=True, detail=f"{ex['result_ref']} withdrawn")
    finally:
        conn.close()
