"""[MOCK] SIMULATED device advisor + field-team device-upgrade request (DEVICE_UPGRADE_PLAN.md).

advise(merchant_id)            -> DeviceAdvice    deterministic, from cashflow_features + gmv_30d + current device
request_device_upgrade(...)    -> DeviceRequest   writes device_offers (accepted) + a field-team ticket
record_declined_device_offer() -> str             'declined' row: starts the shared sales cooling-off
cancel_device_request(token)   -> RollbackResult  rollback: offer cancelled, ticket voided

No price is shown in the prototype (team decision, 31 Oct): the field team quotes it.
Owner: Member 1 · Contract: CONTRACTS C3
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from chaukas import db
from chaukas.core.models import DeviceAdvice, RollbackResult
from chaukas.integrations import ticketing
from chaukas.integrations._common import deterministic_id, execution_by_token, load_config, stored_ref

DEVICE_LABEL = {"qr": "QR", "soundbox": "Soundbox", "ai_soundbox": "AI Soundbox", "pos": "POS machine"}


class DeviceRequest(BaseModel):
    request_id: str   # "DEV-12345"
    ticket_id: str


def advise(merchant_id: str) -> DeviceAdvice:
    """Which device the merchant's own transaction pattern points to. Reads only allowed inputs (fairness)."""
    cfg = load_config("device_advisor")
    conn = db.connect()  # cashflow features + gmv + current device ONLY (fairness; tests/test_fairness.py)
    try:
        f = conn.execute("SELECT * FROM cashflow_features WHERE merchant_id=?", (merchant_id,)).fetchone()
        m = conn.execute("SELECT gmv_30d, device FROM merchants WHERE merchant_id=?", (merchant_id,)).fetchone()
    finally:
        conn.close()
    current = (m["device"] if m else None) or ""
    if not f or not m or f["txn_count_30d"] <= 0 or f["active_days_30d"] <= 0:
        return DeviceAdvice(recommended=False, from_device=current, reason_codes=["NO_TRANSACTION_DATA"],
                            avg_bill_inr=0, txn_per_active_day=0.0, txn_count_30d=0)
    avg_bill = m["gmv_30d"] // f["txn_count_30d"]
    per_day = f["txn_count_30d"] / f["active_days_30d"]  # compared UNROUNDED (6.96 is not 7)
    out = dict(from_device=current, avg_bill_inr=avg_bill, txn_per_active_day=round(per_day, 1),
               txn_count_30d=f["txn_count_30d"])
    for path in (cfg.get("upgrade_paths") or {}).get(current) or []:
        w = path["when"]
        ok = (f["active_days_30d"] >= w.get("min_active_days_30d", 0)
              and per_day >= w.get("min_txn_per_active_day", 0)
              and avg_bill <= w.get("max_avg_bill_inr", avg_bill)
              and avg_bill >= w.get("min_avg_bill_inr", 0)
              and m["gmv_30d"] >= w.get("min_gmv_30d", 0))
        if ok:
            return DeviceAdvice(recommended=True, to_device=path["to"], reason_codes=[path["reason"]], **out)
    why = "LOW_ACTIVITY" if f["active_days_30d"] < 20 else "NO_UPGRADE_NEEDED"
    return DeviceAdvice(recommended=False, reason_codes=[why], **out)


def wants_device_upgrade(text: str) -> bool:
    """Did the merchant ask for a new device in their own words? Keywords from config (no LLM)."""
    low = (text or "").lower()
    return any(k.lower() in low for k in load_config("device_advisor").get("upgrade_keywords") or [])


def request_device_upgrade(merchant_id: str, from_device: str, to_device: str, reason_codes: list[str],
                           session_id: str, idempotency_key: str, offer_shown_at: str | None,
                           trace_id: str | None = None) -> DeviceRequest:
    """Record the merchant's yes and open a ticket for the field team. Only valid after the offer was shown."""
    if not offer_shown_at:
        raise ValueError("the device offer must be shown before the yes (offer_shown_at missing)")
    conn = db.connect()
    try:
        prior = stored_ref(conn, idempotency_key)
        if prior:  # idempotent replay
            row = conn.execute("SELECT ticket_id FROM device_offers WHERE id=?", (prior,)).fetchone()
            return DeviceRequest(request_id=prior, ticket_id=row["ticket_id"] if row else "")
    finally:
        conn.close()
    issue = f"Device upgrade request: {DEVICE_LABEL.get(from_device, from_device)} -> {DEVICE_LABEL.get(to_device, to_device)}"
    ticket = ticketing.raise_ticket(merchant_id, issue, None, session_id, f"{idempotency_key}:ticket")
    conn = db.connect()
    try:
        request_id = deterministic_id(conn, "DEV", idempotency_key, "device_offers")
        conn.execute(
            """INSERT INTO device_offers (id, merchant_id, session_id, trace_id, from_device, to_device, reason_codes,
                   offer_shown_at, consent_at, ticket_id, status) VALUES (?,?,?,?,?,?,?,?,?,?, 'accepted')""",
            (request_id, merchant_id, session_id, trace_id, from_device, to_device, json.dumps(reason_codes),
             offer_shown_at, db.now_iso(), ticket.ticket_id))
        conn.commit()
        return DeviceRequest(request_id=request_id, ticket_id=ticket.ticket_id)
    finally:
        conn.close()


def record_declined_device_offer(merchant_id: str, from_device: str, to_device: str, session_id: str,
                                 trace_id: str | None, offer_shown_at: str | None) -> str:
    """Merchant said no: a 'declined' row starts the shared sales cooling-off (guardrail OFFER_COOLING_OFF)."""
    conn = db.connect()
    try:
        request_id = deterministic_id(conn, "DEV", f"declined:{session_id}:{to_device}", "device_offers")
        conn.execute(
            """INSERT INTO device_offers (id, merchant_id, session_id, trace_id, from_device, to_device,
                   offer_shown_at, declined_at, status) VALUES (?,?,?,?,?,?,?,?, 'declined')""",
            (request_id, merchant_id, session_id, trace_id, from_device, to_device, offer_shown_at, db.now_iso()))
        conn.commit()
        return request_id
    finally:
        conn.close()


def get_request(request_id: str) -> dict | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM device_offers WHERE id=?", (request_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def cancel_device_request(rollback_token: str) -> RollbackResult:
    conn = db.connect()
    try:
        ex = execution_by_token(conn, rollback_token)
        if not ex or not ex["result_ref"]:
            return RollbackResult(ok=True, detail="nothing to roll back")
        row = conn.execute("SELECT ticket_id FROM device_offers WHERE id=?", (ex["result_ref"],)).fetchone()
        conn.execute("UPDATE device_offers SET status='cancelled' WHERE id=?", (ex["result_ref"],))
        if row and row["ticket_id"]:
            conn.execute("UPDATE tickets SET status='closed', resolution='voided by rollback', resolved_by='agent', "
                         "resolved_at=? WHERE id=?", (db.now_iso(), row["ticket_id"]))
        conn.commit()
        return RollbackResult(ok=True, detail=f"{ex['result_ref']} cancelled")
    finally:
        conn.close()
