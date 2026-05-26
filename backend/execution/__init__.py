"""
Execution layer — routes to OANDA or MT5 based on EXECUTOR config.

Usage:
    from backend.execution import get_current_price, get_candles, place_market_order, ...

All functions have identical signatures regardless of backend.
"""
from backend.config import EXECUTOR

if EXECUTOR == "mt5":
    from backend.execution.mt5_executor import (
        get_current_price,
        get_account_summary,
        get_open_trades,
        get_candles,
        place_market_order,
        modify_stop_loss,
        close_trade,
        get_trade_details,
        is_connected,
    )
else:
    from backend.execution.oanda_executor import (
        get_current_price,
        get_account_summary,
        get_open_trades,
        get_candles,
        place_market_order,
        modify_stop_loss,
        close_trade,
        get_trade_details,
    )

    def is_connected():
        return True