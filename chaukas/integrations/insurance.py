"""[MOCK] insurance partner: which shop insurance fits a merchant, and the lead record after the merchant's yes.

recommend()      deterministic rules over fresh DB facts (business category, sales, device, past support tickets) and
                 config/insurance_sim.yaml. No LLM. The guardrail calls the SAME function (check 7), so the offer the
                 agent makes and the offer the guardrail allows can never disagree.
create_lead()    records "merchant said yes" (status interested). Chaukas never issues a policy and never charges a
                 premium: the insurer partner follows up. Rolled back by withdraw_lead().
record_declined() a "no": starts the cooling-off window, like a declined loan offer.

All cover / premium numbers are ILLUSTRATIVE placeholders (config/insurance_sim.yaml). Money is int rupees.

Owner: Member 1 (integration, like lending.py) · rules written by Member 2 · COMPLIANCE.md I1-I4
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from chaukas import db
from chaukas.core.models import RollbackResult
from chaukas.integrations._common import deterministic_id, execution_by_token, load_config, stored_ref

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _cover(gmv: int, multiple: float, round_to: int, cap: int) -> int:
    """Sum insured: `multiple` x monthly sales, rounded down to `round_to`, never below one step, never above `cap`."""
    return max(round_to, min(int(gmv * multiple) // round_to * round_to, cap))


def _premium(cover: int, rate_pct: float) -> int:
    return int(round(cover * rate_pct / 100))


def _device_ticket_count(conn: sqlite3.Connection, merchant_id: str, keywords: list[str]) -> int:
    """Past support tickets about a device (the 'past case' signal)."""
    rx = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.I)
    rows = conn.execute("SELECT issue FROM tickets WHERE merchant_id = ?", (merchant_id,)).fetchall()
    return sum(1 for r in rows if rx.search(r["issue"] or ""))


def _fits(pid: str, p: dict, m: sqlite3.Row, device_tickets: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    cats = p.get("categories")
    if cats is not None:
        if m["business_category"] not in cats:
            return False, []
        reasons.append("CATEGORY_" + m["business_category"].upper())
    if "min_gmv_30d" in p:
        if m["gmv_30d"] < p["min_gmv_30d"]:
            return False, []
        reasons.append("GMV_OK")
    if p.get("requires_device"):
        if not m["device"]:
            return False, []
        reasons.append("HAS_DEVICE")
    if p.get("requires_device_ticket"):
        if device_tickets < 1:
            return False, []
        reasons.append("DEVICE_TICKET_HISTORY")
    if pid == "SHOP_FIRE":
        reasons.insert(0, "PHYSICAL_SHOP")
    return True, reasons


def _view(cfg: dict, pid: str, p: dict, gmv: int, reasons: list[str], alternatives: list[str]) -> dict:
    if "cover_inr" in p:
        cover, premium = p["cover_inr"], p["premium_inr"]
    else:
        cover = _cover(gmv, p["cover_multiple_of_gmv"], p["round_to"], p["max_cover_inr"])
        premium = _premium(cover, p["premium_rate_pct"])
    return {"product_id": pid, "product_name": p["name"], "insurer_name": cfg["insurer_name"],
            "cover_inr": cover, "premium_inr": premium, "covers": list(p["covers"]), "reasons": reasons,
            "grievance_contact": cfg["grievance_contact"], "alternatives": alternatives}


def recommend(conn: sqlite3.Connection, merchant_id: str) -> dict | None:
    """The one product that fits this merchant best (config `priority`), or None if nothing fits. Fresh DB read."""
    cfg = load_config("insurance_sim")
    m = conn.execute("SELECT business_category, device, gmv_30d FROM merchants WHERE merchant_id = ?",
                     (merchant_id,)).fetchone()
    if m is None or not m["business_category"]:
        return None
    tickets = _device_ticket_count(conn, merchant_id, cfg["device_ticket_keywords"])
    fitting: list[tuple[str, dict, list[str]]] = []
    for pid in cfg["priority"]:
        ok, reasons = _fits(pid, cfg["products"][pid], m, tickets)
        if ok:
            fitting.append((pid, cfg["products"][pid], reasons))
    if not fitting:
        return None
    pid, p, reasons = fitting[0]
    return _view(cfg, pid, p, m["gmv_30d"], reasons, [x[0] for x in fitting[1:]])


def recommend_for(merchant_id: str) -> dict | None:
    conn = db.connect()
    try:
        return recommend(conn, merchant_id)
    finally:
        conn.close()


def has_open_lead(conn: sqlite3.Connection, merchant_id: str, product_id: str) -> bool:
    return conn.execute("SELECT 1 FROM insurance_leads WHERE merchant_id = ? AND product_id = ? "
                        "AND status = 'interested'", (merchant_id, product_id)).fetchone() is not None


def declined_recently(conn: sqlite3.Connection, merchant_id: str, now: datetime, days: int) -> bool:
    cutoff = (now - timedelta(days=days)).strftime(_ISO)
    return conn.execute("SELECT 1 FROM insurance_leads WHERE merchant_id = ? AND status = 'declined' "
                        "AND declined_at >= ?", (merchant_id, cutoff)).fetchone() is not None


def create_lead(merchant_id: str, product_id: str, session_id: str, idempotency_key: str,
                trace_id: str | None = None) -> str:
    """Record the merchant's YES. Numbers are re-read from the DB now, never taken from the message."""
    conn = db.connect()
    try:
        prior = stored_ref(conn, idempotency_key)
        if prior:
            return prior
        same = conn.execute("SELECT id FROM insurance_leads WHERE merchant_id = ? AND product_id = ? AND session_id = ? "
                            "AND status = 'interested'", (merchant_id, product_id, session_id)).fetchone()
        if same:                       # the same yes in the same conversation never makes a second lead
            return same["id"]
        view = recommend(conn, merchant_id)
        if view is None or view["product_id"] != product_id:
            raise ValueError("this product is not (or no longer) recommended for the merchant")
        lead_id = deterministic_id(conn, "INS", idempotency_key, "insurance_leads")
        conn.execute(
            """INSERT INTO insurance_leads (id, merchant_id, product_id, product_name, insurer_name, cover_inr,
                   premium_inr, reasons_json, session_id, trace_id, consent_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead_id, merchant_id, product_id, view["product_name"], view["insurer_name"], view["cover_inr"],
             view["premium_inr"], json.dumps(view["reasons"]), session_id, trace_id, db.now_iso(), "interested"))
        conn.commit()
        return lead_id
    finally:
        conn.close()


def record_declined(merchant_id: str, product_id: str, session_id: str, trace_id: str | None) -> str | None:
    """The merchant said no to a presented offer: store it so the cooling-off window starts. Not a guarded action."""
    conn = db.connect()
    try:
        view = recommend(conn, merchant_id)
        if view is None or view["product_id"] != product_id:
            return None
        lead_id = deterministic_id(conn, "INS", f"declined:{session_id}:{product_id}", "insurance_leads")
        conn.execute(
            """INSERT INTO insurance_leads (id, merchant_id, product_id, product_name, insurer_name, cover_inr,
                   premium_inr, reasons_json, session_id, trace_id, declined_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead_id, merchant_id, product_id, view["product_name"], view["insurer_name"], view["cover_inr"],
             view["premium_inr"], json.dumps(view["reasons"]), session_id, trace_id, db.now_iso(), "declined"))
        conn.commit()
        return lead_id
    finally:
        conn.close()


def get_lead(lead_id: str) -> dict | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM insurance_leads WHERE id = ?", (lead_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    lead = dict(row)
    lead["reasons"] = json.loads(lead.pop("reasons_json") or "[]")
    return lead


def withdraw_lead(rollback_token: str) -> RollbackResult:
    conn = db.connect()
    try:
        ex = execution_by_token(conn, rollback_token)
        if not ex or not ex["result_ref"]:
            return RollbackResult(ok=True, detail="nothing to roll back")
        conn.execute("UPDATE insurance_leads SET status = 'withdrawn' WHERE id = ?", (ex["result_ref"],))
        conn.commit()
        return RollbackResult(ok=True, detail=f"{ex['result_ref']} withdrawn")
    finally:
        conn.close()
