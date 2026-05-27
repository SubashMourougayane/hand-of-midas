"""GoldDigger Micro — FastAPI entry point (port 5055)."""
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
    from scanner.price_stream import start_stream, stop_stream

    print("Starting Micro Alpha-Sweep scheduler...")
    start_scheduler()
    start_stream()
    print("GoldDigger Micro ready.")
    yield
    print("Shutting down Micro...")
    stop_stream()
    stop_scheduler()


app = FastAPI(title="GoldDigger Micro", version="1.0.0", lifespan=lifespan)

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

app.include_router(stream_router, prefix="/api/micro")
app.include_router(scan_status_router, prefix="/api/micro")
app.include_router(state_router, prefix="/api/micro")
app.include_router(trades_router, prefix="/api/micro")
app.include_router(journal_router, prefix="/api/micro")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "golddigger-micro", "instrument": "XAU_USD"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5055, reload=False)
