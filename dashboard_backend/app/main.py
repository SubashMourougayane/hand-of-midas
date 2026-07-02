"""FastAPI app entry — mounts routers, starts asyncpg listener, serves SPA build."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import account, bars, runs, signals, trades
from .ws.live import broker, router as ws_router
from .ws.price_stream import PriceStreamer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


price_streamer = PriceStreamer(broker)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await broker.start()
        log.info("broker started")
    except Exception:
        log.exception("broker start failed (DB may be down or NOTIFY triggers missing)")
    try:
        await price_streamer.start()
    except Exception:
        log.exception("price streamer start failed")
    yield
    await price_streamer.stop()
    await broker.stop()
    log.info("broker + price streamer stopped")


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
app.include_router(bars.router)
app.include_router(ws_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve built SPA (dashboard/dist) if present.
#
# Strategy:
#   - /assets/* → StaticFiles (CSS, JS, images)
#   - /api/* and /ws/* → already routed above
#   - everything else → index.html (so React Router can handle /live, /journal,
#     /trades, /signals, /journal?trade=… etc.)
#
# This is the standard SPA-on-FastAPI pattern. StaticFiles(html=True) alone
# only serves index.html at exactly `/`, not at sub-paths, which breaks
# client-side routing on hard-reload.
SPA_DIST = Path(__file__).parent.parent.parent / "dashboard" / "dist"
if SPA_DIST.is_dir():
    SPA_INDEX = SPA_DIST / "index.html"
    app.mount("/assets", StaticFiles(directory=str(SPA_DIST / "assets")), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # Don't shadow api/ws (those are matched before this catch-all due to
        # FastAPI route ordering — but be defensive in case the order changes).
        if full_path.startswith(("api/", "ws/", "assets/")):
            raise HTTPException(status_code=404)
        # Serve a real static file at the requested path if it exists
        # (favicon, robots.txt, vite.svg, etc.). Otherwise → index.html.
        candidate = SPA_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(SPA_INDEX))

    log.info("mounted SPA at / from %s (with /live, /journal etc. fallback)", SPA_DIST)
else:
    @app.get("/")
    def root_placeholder() -> dict:
        return {"hint": f"build the SPA in {SPA_DIST} or visit /api/health"}
