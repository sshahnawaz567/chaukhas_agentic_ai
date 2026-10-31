"""The web frontend runs on another origin (Vercel), so the API must answer CORS preflights.

Owner: Member 1 file (chaukas/main.py), added at the team's request.
"""
from fastapi.testclient import TestClient

from chaukas.main import app


def test_preflight_from_another_origin_is_allowed():
    r = TestClient(app).options("/api/sessions", headers={
        "Origin": "https://chaukas.vercel.app", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in ("*", "https://chaukas.vercel.app")


def test_normal_response_carries_the_cors_header():
    r = TestClient(app).get("/health", headers={"Origin": "https://chaukas.vercel.app"})
    assert r.status_code == 200 and "access-control-allow-origin" in r.headers
