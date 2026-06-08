"""Oil Micro SSE Stream — pushes live state + scan-status every 5s."""
import asyncio
import json
import time
import threading
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from routes.state import get_state
from routes.scan_status import get_scan_status

router = APIRouter()

_live_data = {"state": None, "scan": None, "ts": 0}
_UPDATE_INTERVAL = 5
_thread_started = False


def _refresh_loop():
    while True:
        try:
            scan = get_scan_status()
            state = get_state()
            if scan and "error" not in scan:
                _live_data["scan"] = scan
            if state:
                _live_data["state"] = state
            _live_data["ts"] = time.time()
        except Exception:
            pass
        time.sleep(_UPDATE_INTERVAL)


def _ensure_thread():
    global _thread_started
    if not _thread_started:
        _thread_started = True
        t = threading.Thread(target=_refresh_loop, daemon=True)
        t.start()


@router.get("/stream")
async def stream():
    """SSE endpoint — pushes combined state+scan every 5 seconds."""
    _ensure_thread()

    async def event_generator():
        last_ts = 0
        while True:
            if _live_data["ts"] > last_ts and _live_data["state"] and _live_data["scan"]:
                payload = {"state": _live_data["state"], "scan": _live_data["scan"]}
                yield f"data: {json.dumps(payload, default=str)}\n\n"
                last_ts = _live_data["ts"]
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
