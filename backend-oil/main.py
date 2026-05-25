"""OilMiner — FastAPI entry point (port 5054)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backtest.engine import _get_cached_data
    from scanner.scheduler import start_scheduler, stop_scheduler
    from scanner.price_stream import start_stream, stop_stream

    print("Pre-loading Oil market data...")
    _get_cached_data()
    print("Starting Oil trading scheduler...")
    start_scheduler()
    print("Starting Oil price stream...")
    start_stream()
    print("OilMiner ready.")
    yield
    print("Shutting down OilMiner...")
    stop_stream()
    stop_scheduler()


app = FastAPI(title="OilMiner", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.backtest import router as backtest_router
from routes.state import router as state_router
from routes.trades import router as trades_router
from routes.journal import router as journal_router
from routes.journey import router as journey_router
from routes.scan_status import router as scan_status_router

app.include_router(backtest_router, prefix="/api/oil")
app.include_router(state_router, prefix="/api/oil")
app.include_router(trades_router, prefix="/api/oil")
app.include_router(journal_router, prefix="/api/oil")
app.include_router(journey_router, prefix="/api/oil")
app.include_router(scan_status_router, prefix="/api/oil")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "oilminer", "instrument": "BCO_USD"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5054, reload=False)
