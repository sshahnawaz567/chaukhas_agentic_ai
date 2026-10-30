"""[MOCK] verify_ledger, retrigger_payout, cancel_payout (rollback).

Owner: Member 1 · Contract: CONTRACTS C3
"""
from __future__ import annotations

from chaukas import db
from chaukas.core.models import LedgerStatus, PayoutResult, RollbackResult
from chaukas.integrations._common import execution_by_token, load_config, stored_ref


def verify_ledger(settlement_id: str) -> LedgerStatus:
    """Read-only. Always reads the settlement row fresh."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return LedgerStatus(found=False)
    return LedgerStatus(found=True, status=row["status"], amount=row["amount"],
                        cause=row["cause"], retry_count=row["retry_count"])


def retrigger_payout(settlement_id: str, amount: int, account_ref: str,
                     idempotency_key: str) -> PayoutResult:
    """Re-send a failed settlement. `account_ref` is the DETOKENISED payout account (only the
    Action agent has it); the mock never stores or logs it."""
    conn = db.connect()
    try:
        prior = stored_ref(conn, idempotency_key)
        if prior:  # idempotent replay: same key -> same result, no second payout
            return PayoutResult(status="success", payout_ref=prior)

        if settlement_id in (load_config("mock").get("fail_ids") or []):
            return PayoutResult(status="failed", error="simulated payout failure (mock fail_ids)")

        row = conn.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone()
        if not row:
            return PayoutResult(status="failed", error="settlement not found")
        if row["status"] != "failed" or row["amount"] != amount or not account_ref:
            return PayoutResult(status="failed", error="payout rejected by mock bank")

        payout_ref = f"PAY-{settlement_id[-5:]}-{row['retry_count'] + 1}"
        conn.execute(
            "UPDATE settlements SET status='retriggered', retry_count=retry_count+1, payout_ref=?, updated_at=? WHERE id=?",
            (payout_ref, db.now_iso(), settlement_id),
        )
        conn.commit()
        return PayoutResult(status="success", payout_ref=payout_ref)
    finally:
        conn.close()


def cancel_payout(rollback_token: str) -> RollbackResult:
    """Undo a retrigger: settlement goes back to 'failed'. Safe to call when nothing was sent."""
    conn = db.connect()
    try:
        ex = execution_by_token(conn, rollback_token)
        if not ex or not ex["result_ref"]:
            return RollbackResult(ok=True, detail="nothing to roll back")
        cur = conn.execute(
            """UPDATE settlements SET status='failed', payout_ref=NULL,
                      retry_count=MAX(retry_count-1,0), updated_at=? WHERE payout_ref=?""",
            (db.now_iso(), ex["result_ref"]),
        )
        conn.commit()
        detail = f"payout {ex['result_ref']} cancelled" if cur.rowcount else "payout already reversed"
        return RollbackResult(ok=True, detail=detail)
    finally:
        conn.close()
