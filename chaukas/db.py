"""SQLite connection helper. Sets PRAGMA foreign_keys=ON on EVERY connection.
Small query helpers used by context, guardrail, audit.

Owner: Member 2 · Contract: C0 / schema.sql
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "chaukas.db"


def db_path() -> str:
    """DB location: CHAUKAS_DB_PATH from .env / environment, else data/chaukas.db."""
    return os.environ.get("CHAUKAS_DB_PATH") or str(DEFAULT_DB_PATH)


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Open a connection. foreign_keys is PER CONNECTION in SQLite, so it is set here, always."""
    conn = sqlite3.connect(str(path) if path else db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso() -> str:
    """Current time as ISO-8601 UTC, the format every timestamp column uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_all(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchall()


def query_one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, tuple(params)).fetchone()


def execute(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    """Run one write. Caller owns commit() so related writes can share a transaction."""
    return conn.execute(sql, tuple(params))
