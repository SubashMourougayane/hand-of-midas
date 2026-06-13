"""OilMiner Micro — FastAPI entry point (port 5056)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    from scanner.scheduler import start_scheduler, stop_scheduler

    EXECUTOR = os.getenv("EXECUTOR", "oanda")

    print("Starting Oil Micro Alpha-Sweep scheduler...")
    start_scheduler()

    stop_stream = None
    if EXECUTOR != "mt5":
        from scanner.price_stream import start_stream, stop_stream as _stop_stream
        stop_stream = _stop_stream
        print("Starting Oil Micro OANDA price stream...")
        start_stream()
    else:
        print("MT5 mode — OANDA price stream disabled (DWX provides prices)")

    print("OilMiner Micro ready.")
    yield
    print("Shutting down OilMiner Micro...")
    if stop_stream is not None:
        stop_stream()
    stop_scheduler()


app = FastAPI(title="OilMiner Micro", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.state import router as state_router
from routes.scan_status import router as scan_status_router
from routes.trades import router as trades_router
from routes.journal import router as journal_router
from routes.stream import router as stream_router
from routes.backtest import router as backtest_router

app.include_router(stream_router, prefix="/api/oil-micro")
app.include_router(scan_status_router, prefix="/api/oil-micro")
app.include_router(backtest_router, prefix="/api/oil-micro")
app.include_router(state_router, prefix="/api/oil-micro")
app.include_router(trades_router, prefix="/api/oil-micro")
app.include_router(journal_router, prefix="/api/oil-micro")

from backend_common.debug_router import build_debug_router, DebugConfig
import config as _omicro_cfg
from scanner import scheduler as _omicro_sched
from backend import db as _omicro_db


def _omicro_dwx_dir():
    try:
        from backend.execution.mt5_executor import DWX_DIR
        return DWX_DIR
    except Exception:
        return None


app.include_router(build_debug_router(DebugConfig(
    service_name="oil-micro",
    log_filename="oil-micro.log",
    repo_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    instrument="BCO_USD",
    strategies=["micro_alpha_sweep_oil"],
    trade_ref_prefix="OIL-MI-",
    db_execute=_omicro_db.execute,
    config_module=_omicro_cfg,
    scheduler_module=_omicro_sched,
    dwx_dir_getter=_omicro_dwx_dir,
)), prefix="/api/oil-micro/debug")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "oilminer-micro", "instrument": "BCO_USD"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5056, reload=False, timeout_keep_alive=600)
