"""Oil State API — GET /api/oil/state."""
from fastapi import APIRouter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.execution.oanda_executor import get_current_price, get_account_summary, get_open_trades

router = APIRouter()


@router.get("/state")
def get_state():
    price = get_current_price(instrument="BCO_USD")
    account = get_account_summary()
    positions = get_open_trades(instrument="BCO_USD")

    return {
        "price": price,
        "account": account,
        "oanda_positions": positions,
        "instrument": "BCO_USD",
        "scheduler_active": True,
    }
