"""Micro Backtest API — stub until full Micro backtest engine is built."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/backtest/latest")
def get_latest():
    return {"result": None}


@router.post("/backtest")
def run_backtest():
    return JSONResponse(
        status_code=501,
        content={"error": "Micro backtest not yet implemented. Use scripts/compare_strategies.py for now."},
    )
