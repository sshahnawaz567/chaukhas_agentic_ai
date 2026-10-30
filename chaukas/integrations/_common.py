"""Helpers shared by the [MOCK] integrations: deterministic ids, idempotent replay lookup,
config loading. Mocks are deterministic: same input -> same output.

Owner: Member 1 · Contract: CONTRACTS C3
"""
from __future__ import annotations

import hashlib
import sqlite3
from functools import lru_cache

import yaml

from chaukas.db import ROOT


@lru_cache(maxsize=None)
def load_config(name: str) -> dict:
    """config/{name}.yaml (cached: config is static, money state is NEVER cached here)."""
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8")) or {}


def stored_ref(conn: sqlite3.Connection, idempotency_key: str) -> str | None:
    """result_ref of an earlier execution with this key, if it already produced one."""
    row = conn.execute("SELECT result_ref FROM executions WHERE idempotency_key=?",
                       (idempotency_key,)).fetchone()
    return row["result_ref"] if row and row["result_ref"] else None


def execution_by_token(conn: sqlite3.Connection, rollback_token: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM executions WHERE rollback_token=?", (rollback_token,)).fetchone()


def deterministic_id(conn: sqlite3.Connection, prefix: str, seed: str, table: str, column: str = "id") -> str:
    """'TKT-12345' derived from `seed`; linear-probes if that id already exists."""
    n = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 90000 + 10000
    while True:
        candidate = f"{prefix}-{n}"
        if not conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (candidate,)).fetchone():
            return candidate
        n = n + 1 if n < 99999 else 10000
