"""Deployment: Render blueprint, pinned requirements, CORS, the public-demo guard, and the smoke test itself.

Owner: Member 2 · DEPLOY.md
"""
import importlib
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from chaukas.db import ROOT
from eval import smoke_deployed

BLUEPRINT = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
SERVICE = BLUEPRINT["services"][0]
ENV = {e["key"]: e for e in SERVICE["envVars"]}


# ------------------------------------------------------------------ the Render blueprint

def test_the_service_runs_one_worker_because_the_pii_vault_and_counters_live_in_memory():
    cmd = SERVICE["startCommand"]
    assert "chaukas.main:app" in cmd and "--workers 1" in cmd and "$PORT" in cmd and "0.0.0.0" in cmd


def test_health_check_points_at_the_real_health_route():
    assert SERVICE["healthCheckPath"] == "/health"


def test_secrets_are_asked_for_in_the_dashboard_never_written_in_the_file():
    for key in ("SARVAM_API_KEY", "GEMINI_API_KEY"):
        assert ENV[key].get("sync") is False and "value" not in ENV[key]
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert not re.search(r"sk[-_][A-Za-z0-9]{10,}", text)


def test_the_public_demo_switch_is_on_and_live_llm_is_the_default():
    assert str(ENV["CHAUKAS_PUBLIC_DEMO"]["value"]) == "1"
    assert str(ENV["CHAUKAS_REPLAY_MODE"]["value"]) == "off"
    assert ENV["PYTHON_VERSION"]["value"].startswith("3.11")


def test_the_build_installs_the_pinned_file_and_fills_the_scorecard():
    build = " ".join(SERVICE["buildCommand"].split())
    assert "requirements-deploy.txt" in build and "eval.run_eval --llm replay" in build
    assert "test -f eval/latest.json" in build            # a missed metric exits 1: it must not fail the build, a missing file must
    assert "&& python -m eval.run_eval" not in build


def test_deploy_requirements_are_all_pinned_and_cover_the_runtime_imports():
    lines = [l.strip() for l in (ROOT / "requirements-deploy.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    assert lines and all("==" in l for l in lines)
    names = {re.split(r"[=\[]", l)[0].lower() for l in lines}
    assert {"fastapi", "uvicorn", "pydantic", "pyyaml", "openai", "httpx", "python-dotenv"} <= names
    dev = {re.split(r"[=<>\[]", l)[0].lower() for l in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
           if l.strip() and not l.startswith("#")} - {"pytest"}
    assert dev <= names, dev - names              # nothing the app needs is missing from the deploy file


def test_no_secret_or_database_is_tracked_by_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^\.env$", ignore, re.M) and "data/*.db" in ignore


# ------------------------------------------------------------------ CORS: closed by default, exact origins when set

def _fresh_app(monkeypatch, origins):
    import chaukas.main as main
    if origins is None:
        monkeypatch.delenv("CHAUKAS_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CHAUKAS_CORS_ORIGINS", origins)
    return importlib.reload(main).app


@pytest.fixture(autouse=True)
def _restore_main(monkeypatch):
    yield
    monkeypatch.delenv("CHAUKAS_CORS_ORIGINS", raising=False)
    import chaukas.main as main
    importlib.reload(main)


def test_cors_is_closed_unless_an_origin_is_configured(monkeypatch):
    c = TestClient(_fresh_app(monkeypatch, None))
    r = c.get("/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_only_the_configured_origin_is_allowed(monkeypatch):
    c = TestClient(_fresh_app(monkeypatch, "https://chaukas-ui.vercel.app, https://second.example"))
    ok = c.options("/api/merchants", headers={"Origin": "https://chaukas-ui.vercel.app", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://chaukas-ui.vercel.app"
    bad = c.options("/api/merchants", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
    assert c.get("/health", headers={"Origin": "https://evil.example"}).headers.get("access-control-allow-origin") is None


def test_a_wildcard_is_never_used_by_the_code():
    assert '"*"' not in (ROOT / "chaukas" / "main.py").read_text(encoding="utf-8").split("_cors_origins")[1].split("\n\n")[0]


# ------------------------------------------------------------------ the public-demo guard

@pytest.fixture
def api(tmp_path, monkeypatch):
    from data.seed import seed
    path = tmp_path / "deploy.db"
    seed(path)
    monkeypatch.setenv("CHAUKAS_DB_PATH", str(path))
    monkeypatch.setenv("CHAUKAS_AGENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CHAUKAS_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("CHAUKAS_EVAL_PATH", str(ROOT / "eval" / "latest.json"))
    from chaukas.llm import prompt as llm_prompt
    from chaukas.llm.client import LLMUnavailable

    def no_llm(*a, **kw):
        raise LLMUnavailable("offline")
    monkeypatch.setattr(llm_prompt, "complete", no_llm)
    from chaukas.core import m2_shim
    monkeypatch.setattr(m2_shim, "emit_span", lambda span: None)
    import chaukas.main as main
    return TestClient(importlib.reload(main).app), path


def test_erasure_is_refused_on_the_public_demo_and_nothing_changes(api, monkeypatch):
    client, path = api
    monkeypatch.setenv("CHAUKAS_PUBLIC_DEMO", "1")
    r = client.post("/api/merchants/M001/erasure")
    assert r.status_code == 403 and r.json()["error"]["code"] == "DISABLED_IN_PUBLIC_DEMO"
    import sqlite3
    row = sqlite3.connect(path).execute("SELECT name, phone FROM merchants WHERE merchant_id='M001'").fetchone()
    assert row[0] != "Erased merchant" and row[1]


def test_erasure_still_works_off_the_public_demo(api, monkeypatch):
    client, _ = api
    monkeypatch.delenv("CHAUKAS_PUBLIC_DEMO", raising=False)
    assert client.post("/api/merchants/M001/erasure").status_code == 200


# ------------------------------------------------------------------ the smoke test against the app itself

@pytest.fixture
def scorecard(tmp_path):
    """The build step writes eval/latest.json on Render; here a tiny stand-in is enough."""
    import json
    from eval.run_eval import TARGETS
    p = ROOT / "eval" / "latest.json"
    existing = p.exists()
    if not existing:
        p.write_text(json.dumps({k: {"value": 0, "target": "x", "pass": True} for k in TARGETS}), encoding="utf-8")
        (ROOT / "eval" / "latest_detail.json").write_text(json.dumps({"redteam_results": [{"case_id": "x"}], "cases": []}), encoding="utf-8")
    yield
    if not existing:
        p.unlink()
        (ROOT / "eval" / "latest_detail.json").unlink()


def test_the_smoke_test_passes_against_a_healthy_app(api, scorecard, monkeypatch):
    client, _ = api
    monkeypatch.setenv("CHAUKAS_PUBLIC_DEMO", "1")
    results = smoke_deployed.run_smoke(client)
    assert [n for n, ok, d in results if not ok] == [], results


def test_the_full_smoke_test_runs_the_insurance_conversation(api, scorecard):
    client, _ = api
    results = smoke_deployed.run_smoke(client, full=True)
    failed = [(n, d) for n, ok, d in results if not ok]
    assert failed == [] and any(n.startswith("full:") for n, _, _ in results)


def test_the_smoke_test_notices_a_broken_app(api, scorecard, monkeypatch):
    client, path = api
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("UPDATE merchants SET preferred_lang = 'ta-IN' WHERE merchant_id = 'M003'")   # a removed language
    conn.commit()
    failed = [n for n, ok, _ in smoke_deployed.run_smoke(client) if not ok]
    assert "20 merchants, only the five final languages" in failed
# ------------------------------------------------------------------ the guide matches the blueprint

def test_every_env_var_of_the_blueprint_is_explained_in_deploy_md():
    guide = (ROOT / "DEPLOY.md").read_text(encoding="utf-8")
    for key in ENV:
        assert key in guide, key
    assert "--workers 1" in guide and "smoke_deployed" in guide and "vercel.json" in guide
