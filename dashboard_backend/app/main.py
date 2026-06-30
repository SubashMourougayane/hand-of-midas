"""FastAPI app entry — mounts routers, starts asyncpg listener, serves SPA build."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import account, runs, signals, trades
from .ws.live import broker, router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await broker.start()
        log.info("broker started")
    except Exception:
        log.exception("broker start failed (DB may be down or NOTIFY triggers missing)")
    yield
    await broker.stop()
    log.info("broker stopped")


app = FastAPI(title="bt_engine dashboard", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8001"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(runs.router)
app.include_router(trades.router)
app.include_router(signals.router)
app.include_router(account.router)
app.include_router(ws_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve built SPA (dashboard/dist) if present.
SPA_DIST = Path(__file__).parent.parent.parent / "dashboard" / "dist"
if SPA_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(SPA_DIST), html=True), name="spa")
    log.info("mounted SPA at / from %s", SPA_DIST)
else:
    @app.get("/")
    def root_placeholder() -> dict:
        return {"hint": f"build the SPA in {SPA_DIST} or visit /api/health"}
