"""Oil Trades API — placeholder for live trades."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/trades")
def get_trades():
    return {"trades": [], "stats": {}}


@router.get("/trades/backtest")
def get_backtest_trades():
    return {"trades": [], "stats": {}}
