"""Replay mode: record LLM responses for demo scenes to recordings/,
serve them when the network/API fails.

Modes (env CHAUKAS_REPLAY_MODE): off (default) | record | replay
  record -> every successful live response is saved
  replay -> never touch the network; serve the recording or raise a miss
  off    -> live; if every provider fails, a recording (if any) is still served as a safety net

Key = sha1 of a STABLE caller-supplied string (agent + merchant + masked message ...), never of the
full prompt, because prompts contain per-run ids.

Owner: Member 1 · Contract: DEMO_SCRIPT §9
"""
from __future__ import annotations

import hashlib
import json
import os
import threading

from chaukas.db import ROOT

RECORDINGS_DIR = ROOT / "recordings"
_lock = threading.Lock()


def mode() -> str:
    m = (os.environ.get("CHAUKAS_REPLAY_MODE") or "off").strip().lower()
    return m if m in ("off", "record", "replay") else "off"


def _key(replay_key: str) -> str:
    return hashlib.sha1(replay_key.encode("utf-8")).hexdigest()[:16]


def _file(agent: str):
    return RECORDINGS_DIR / f"{agent}.json"


def _load(agent: str) -> dict:
    try:
        return json.loads(_file(agent).read_text(encoding="utf-8"))
    except Exception:
        return {}


def lookup(agent: str, replay_key: str | None) -> str | None:
    if not replay_key:
        return None
    entry = _load(agent).get(_key(replay_key))
    return entry["text"] if entry else None


def record(agent: str, replay_key: str | None, text: str) -> None:
    if not replay_key:
        return
    with _lock:
        RECORDINGS_DIR.mkdir(exist_ok=True)
        data = _load(agent)
        data[_key(replay_key)] = {"key": replay_key, "text": text}
        _file(agent).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
