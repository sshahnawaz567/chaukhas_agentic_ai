"""Context agent (360°): deterministic DB reads, NO LLM. Settlements always fresh.
Returns MerchantContext with tokenised PII.

Owner: Member 1 · Contract: CONTRACTS C1
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from chaukas import db
from chaukas.core import m2_shim
from chaukas.core.models import MerchantContext, SettlementView
from chaukas.integrations import devices
from chaukas.integrations._common import load_config

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _retriggerable(status: str, cause: str | None, settlement_date: str, bank_updated_at: str | None) -> bool:
    """failed AND (BANK_DOWN OR IFSC fixed after the failure). KYC_PENDING is never retriggerable."""
    if status != "failed":
        return False
    if cause == "BANK_DOWN":
        return True
    if cause == "IFSC_MISMATCH":
        return bool(bank_updated_at) and bank_updated_at > settlement_date
    return False


def load(merchant_id: str) -> MerchantContext:
    """Read everything fresh from the DB (never cached) and tokenise PII."""
    conn = db.connect()
    try:
        m = conn.execute("SELECT * FROM merchants WHERE merchant_id=?", (merchant_id,)).fetchone()
        if not m:
            raise LookupError(f"merchant {merchant_id} not found")

        settlements = [
            SettlementView(
                id=r["id"], amount=r["amount"], settlement_date=r["settlement_date"],
                status=r["status"], cause=r["cause"],
                retriggerable=_retriggerable(r["status"], r["cause"], r["settlement_date"],
                                             m["bank_details_updated_at"]),
            )
            for r in conn.execute(
                "SELECT * FROM settlements WHERE merchant_id=? ORDER BY settlement_date DESC", (merchant_id,))
        ]
        tickets = [
            {"id": r["id"], "settlement_id": r["settlement_id"], "issue": m2_shim.scrub(r["issue"]),
             "status": r["status"]}
            for r in conn.execute(
                "SELECT * FROM tickets WHERE merchant_id=? AND status IN ('open','in_progress') "
                "ORDER BY created_at DESC", (merchant_id,))
        ]
        has_open_handoff = conn.execute(
            "SELECT 1 FROM handoffs WHERE merchant_id=? AND status IN ('open','claimed') LIMIT 1",
            (merchant_id,)).fetchone() is not None

        cooling_days = int(_policy().get("offer_cooling_off_days", 7))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=cooling_days)).strftime(_ISO)
        declined_recently = conn.execute(
            "SELECT 1 FROM offers WHERE merchant_id=? AND status='declined' AND declined_at >= ? LIMIT 1",
            (merchant_id, cutoff)).fetchone() is not None
    finally:
        conn.close()

    return MerchantContext(
        merchant_id=merchant_id,
        name_masked=m2_shim.mask(m["name"], "name"),
        account_ref=m2_shim.tokenise(m["account_no"], "account_no") if m["account_no"] else "",
        preferred_lang=m["preferred_lang"], kyc_status=m["kyc_status"], device=m["device"],
        gmv_30d=m["gmv_30d"], bank_details_updated_at=m["bank_details_updated_at"],
        settlements=settlements, open_tickets=tickets, has_open_handoff=has_open_handoff,
        declined_offer_recently=declined_recently,
        device_advice=devices.advise(merchant_id),  # deterministic, fresh every turn (DEVICE_UPGRADE_PLAN.md)
    )


def _policy() -> dict:
    """config/policy.yaml is Member 2's; we only READ offer_cooling_off_days from it."""
    try:
        return load_config("policy")
    except Exception:
        return {}
