"""Event watcher: finds failed settlements nobody has told the merchant about yet, and starts a proactive
session for each one (orchestrator.handle_event). Deterministic, no LLM, read-only on money state.

- Reads the settlements TABLE, fresh (CLAUDE.md rule 4), never merchant_fixtures.json: after a retrigger the
  row is 'retriggered' while the JSON still says 'failed', so the JSON would notify the merchant forever.
- Only status='failed' is a trigger (v1). 'pending' (bank down, waiting) is not.
- Dedupe: one proactive session per settlement, keyed by sessions.trigger_ref = 'settlement_failed:<id>'.
- Runs on demand only (POST /api/events/scan). Production: a ledger event / Kafka consumer (roadmap).

Owner: Member 1 · PROACTIVE_FEATURE_CHANGES.md §4.2
"""
from __future__ import annotations

import threading
from typing import Any

from chaukas import db
from chaukas.core import orchestrator
from chaukas.gateway import session as gw

_scan_lock = threading.Lock()  # two clicks at once must not notify the same settlement twice


def trigger_ref(settlement_id: str) -> str:
    return f"settlement_failed:{settlement_id}"


def find_new_failures(merchant_id: str | None = None) -> list[dict[str, str]]:
    """Failed settlements without a proactive session yet. Raises ProactiveSchemaMissing before schema S5."""
    conn = db.connect()
    try:
        if not gw.has_trigger_columns(conn):
            raise gw.ProactiveSchemaMissing("sessions.trigger_source/trigger_ref missing (schema S5)")
        sql = "SELECT id, merchant_id FROM settlements WHERE status='failed'"
        args: tuple = ()
        if merchant_id:
            sql, args = sql + " AND merchant_id=?", (merchant_id,)
        hits = conn.execute(sql + " ORDER BY merchant_id, id", args).fetchall()
        return [{"merchant_id": h["merchant_id"], "settlement_id": h["id"]} for h in hits
                if not conn.execute("SELECT 1 FROM sessions WHERE trigger_ref=?", (trigger_ref(h["id"]),)).fetchone()]
    finally:
        conn.close()


def scan(merchant_id: str | None = None) -> list[dict[str, Any]]:
    """Notify every new failure: [{merchant_id, settlement_id, session_id, turn: TurnResponse}]."""
    with _scan_lock:
        out = []
        for hit in find_new_failures(merchant_id):
            turn = orchestrator.handle_event(hit["merchant_id"], hit["settlement_id"])
            out.append({**hit, "session_id": turn.session_id, "turn": turn})
        return out
