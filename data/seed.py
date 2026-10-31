"""Build data/chaukas.db from data/schema.sql + data/merchant_fixtures.json.
Converts days_ago -> ISO dates relative to now. Run: python -m data.seed

Owner: Member 2 · Contract: C0
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chaukas.db import ROOT, connect, db_path

SCHEMA_PATH = ROOT / "data" / "schema.sql"
FIXTURES_PATH = ROOT / "data" / "merchant_fixtures.json"

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _ago(now: datetime, days: int | None) -> str | None:
    """days_ago -> ISO-8601 UTC string; None stays None."""
    if days is None:
        return None
    return (now - timedelta(days=days)).strftime(_ISO)


def seed(path: str | os.PathLike | None = None, now: datetime | None = None) -> dict:
    """Drop and rebuild the DB at `path`. Returns row counts so callers can sanity-check."""
    target = Path(path) if path else Path(db_path())
    now = now or datetime.now(timezone.utc)

    if target.exists():
        target.unlink()  # fresh seed every time: demo needs a known state
    target.parent.mkdir(parents=True, exist_ok=True)

    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    conn = connect(target)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")  # executescript can reset session state

        for m in fixtures["merchants"]:
            mid, pii = m["merchant_id"], m["pii"]
            conn.execute(
                """INSERT INTO merchants (merchant_id, name, gmv_30d, device, preferred_lang,
                       kyc_status, business_category, bank_details_updated_at, phone, vpa, pan, account_no, ifsc)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mid, m["name"], m["gmv_30d"], m["device"], m["preferred_lang"], m["kyc_status"],
                 m.get("business_category"),
                 _ago(now, m.get("bank_details_updated_days_ago")),
                 pii["phone"], pii["vpa"], pii["pan"], pii["account_no"], pii["ifsc"]),
            )

            c = m["cashflow"]
            conn.execute(
                """INSERT INTO cashflow_features (merchant_id, txn_count_30d, withdrawals_30d,
                       inflow_30d, outflow_30d, avg_balance, active_days_30d, inflow_cv,
                       account_age_months) VALUES (?,?,?,?,?,?,?,?,?)""",
                (mid, c["txn_count_30d"], c["withdrawals_30d"], c["inflow_30d"], c["outflow_30d"],
                 c["avg_balance"], c["active_days_30d"], c["inflow_cv"], c["account_age_months"]),
            )

            for s in m["settlements"]:
                when = _ago(now, s["days_ago"])
                conn.execute(
                    """INSERT INTO settlements (id, merchant_id, amount, settlement_date, status,
                           cause, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (s["id"], mid, s["amount"], when, s["status"], s["cause"], when, when),
                )

            for t in m["tickets"]:
                when = _ago(now, t["days_ago"])
                conn.execute(
                    """INSERT INTO tickets (id, merchant_id, settlement_id, issue, status, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (t["id"], mid, t["settlement_id"], t["issue"], t["status"], when),
                )

            for o in m["offers"]:
                when = _ago(now, o["days_ago"])
                declined = when if o["status"] == "declined" else None
                conn.execute(
                    """INSERT INTO offers (id, merchant_id, amount, status, declined_at, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (o["id"], mid, o["amount"], o["status"], declined, when),
                )

        conn.commit()
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("merchants", "cashflow_features", "settlements", "tickets", "offers")
        }
    finally:
        conn.close()
    return counts


if __name__ == "__main__":
    out = db_path()
    print(f"Seeded {out}: {seed(out)}")
