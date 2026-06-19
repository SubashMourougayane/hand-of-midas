"""Hand of Midas — General service (port 5050).

Cross-cutting concerns that don't belong to a specific trading system:
  - /api/auth/*   (login, logout, me)        — formerly on Gold Macro 5053
  - /api/health                              — formerly on Gold Macro 5053
  - /api/debug/*  (cross-service aggregator) — formerly on Gold Macro 5053

Pure re-route. NO scheduler. NO DB writes. NO market data load.
This service exists so user-auth survives the Macro retirement (2026-06-19,
commit 8246d08) without re-spawning the dead Macro backend just for auth.

Started by start-win.bat as [1/4]. Killed/rotated alongside the others.
"""
import os
import sys

# Make the legacy `backend.*` import path resolvable from here, so we can
# reuse backend.routes.auth_routes / backend.auth / backend.db as-is without
# any code rewrite. This service is "just a mount point" for those routers.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.auth_routes import router as auth_router
from backend_common.debug_router import build_aggregate_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Hand of Midas General service ready (auth + aggregate debug).")
    yield
    print("Shutting down General service...")


app = FastAPI(title="Hand of Midas General", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "https://midas.subashtrades.in",
        "https://staging.midas.subashtrades.in",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth — login/logout/me. Mounted at /api so endpoints are /api/auth/*
# (matches existing frontend code AuthContext.tsx + Caddy /api/auth/* route).
app.include_router(auth_router, prefix="/api")

# Cross-service debug aggregator — fans out to each system's /api/<sys>/debug.
# Macros now retired so they're absent from the service map; their /debug/*
# endpoints will 502 cleanly via Caddy. Add them back if Macros re-spawn.
app.include_router(build_aggregate_router({
    "micro": "http://localhost:5055",
    "oil-micro": "http://localhost:5056",
}), prefix="/api/debug")


@app.get("/api/health")
def health():
    """Liveness probe — used by Caddy + monitoring."""
    return {
        "ok": True,
        "service": "general",
        "version": "1.0.0",
    }


@app.get("/")
def root():
    """Friendly hint for direct visits."""
    return {
        "service": "Hand of Midas General",
        "endpoints": [
            "/api/auth/login",
            "/api/auth/me",
            "/api/auth/logout",
            "/api/health",
            "/api/debug/all-health",
            "/api/debug/all-state",
            "/api/debug/all-orphans",
            "/api/debug/all-exceptions",
        ],
    }
