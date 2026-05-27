"""GoldDigger — FastAPI entry point (port 5053)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.backtest import router as backtest_router
from backend.routes.state import router as state_router
from backend.routes.trades import router as trades_router
from backend.routes.journal import router as journal_router
from backend.routes.journey import router as journey_router
from backend.routes.auth_routes import router as auth_router
from backend.routes.scan_status import router as scan_status_router
from backend.routes.stream import router as stream_router

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.backtest.engine import _get_cached_data
    from backend.scanner.scheduler import start_scheduler, stop_scheduler
    from backend.config import EXECUTOR

    print("Pre-loading market data for backtest...")
    _get_cached_data()
    print("Starting live trading scheduler...")
    start_scheduler()

    if EXECUTOR != "mt5":
        from backend.scanner.price_stream import start_stream, stop_stream
        print("Starting real-time price stream...")
        start_stream()
    else:
        print("MT5 mode — OANDA price stream disabled (DWX handles prices)")

    print("GoldDigger ready.")
    yield
    print("Shutting down...")
    if EXECUTOR != "mt5":
        stop_stream()
    stop_scheduler()


app = FastAPI(title="GoldDigger", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(stream_router, prefix="/api/gold")
app.include_router(scan_status_router, prefix="/api/gold")
app.include_router(backtest_router, prefix="/api/gold")
app.include_router(state_router, prefix="/api/gold")
app.include_router(trades_router, prefix="/api/gold")
app.include_router(journal_router, prefix="/api/gold")
app.include_router(journey_router, prefix="/api/gold")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "golddigger"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=5053, reload=True, timeout_keep_alive=300)
