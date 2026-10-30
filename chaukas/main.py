"""FastAPI app: creates the app, includes api/* routers, serves ui/ as static files.
Run: uvicorn chaukas.main:app --reload

Owner: Member 1 · Contract: CONTRACTS C5
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from chaukas import db

load_dotenv(db.ROOT / ".env")
logging.basicConfig(level=os.environ.get("CHAUKAS_LOG_LEVEL", "INFO"))

from chaukas.api import chat, desk  # noqa: E402  (after load_dotenv so routers see the env)

@asynccontextmanager
async def _lifespan(_: FastAPI):
    if not Path(db.db_path()).exists():  # convenience: first run seeds the demo DB
        from data.seed import seed

        logging.getLogger("chaukas").info("DB missing -> seeding %s", seed(db.db_path()))
    yield


app = FastAPI(title="Chaukas", version="0.1", lifespan=_lifespan)


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException):
    """C5 error shape: {"error": {"code": ..., "message": ...}}."""
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


app.include_router(chat.router)
app.include_router(desk.router)

try:  # Member 2's ops router (traces / audit / redteam / eval) — mounted once it exists
    from chaukas.api import ops

    if hasattr(ops, "router"):
        app.include_router(ops.router)
except Exception:  # pragma: no cover
    logging.getLogger("chaukas").info("api.ops not available yet (Member 2)")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "replay_mode": os.environ.get("CHAUKAS_REPLAY_MODE", "off")}


_ui = db.ROOT / "ui"
if (_ui / "index.html").exists():
    app.mount("/", StaticFiles(directory=_ui, html=True), name="ui")
