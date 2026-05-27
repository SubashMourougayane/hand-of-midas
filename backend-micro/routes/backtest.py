"""Micro Backtest API — stub until full Micro backtest engine is built."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/backtest/latest")
def get_latest():
    return {"result": None}


@router.post("/backtest")
def run_backtest():
    return {"error": "Micro backtest not yet implemented. Use scripts/compare_strategies.py for now."}
