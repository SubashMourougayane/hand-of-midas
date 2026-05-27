"""
Gold Micro live trading engine — Micro Alpha-Sweep signals with DD protection.
Uses DD state id=3, trade_ref prefix GD-MI-, strategy='micro_alpha_sweep'.
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.execution import (
    get_current_price, place_market_order,
    close_trade, get_open_trades, get_account_summary,
    modify_stop_loss, get_trade_details,
)
from backend.db import execute
from backend import notify
from config import STRATEGY_RISK, MAX_UNITS, MICRO_ALPHA_SWEEP, DD_STATE_ID, TRADE_REF_PREFIX, DD_PROTECTION


def _get_gbp_usd_rate():
    from backend.config import EXECUTOR
    if EXECUTOR == "mt5":
        return 1.0
    from backend.execution.oanda_executor import _get_gbp_usd_rate as _rate
    return _rate()


def _log_signal(strategy: str, direction: str, entry: float, sl: float, tp: float,
                taken: bool, skip_reason: str = "", trade_ref: str = ""):
    execute(
        """INSERT INTO gd_signals (strategy, direction, entry_price, sl_price, tp_price, taken, skip_reason, trade_ref)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (strategy, direction, entry, sl, tp, taken, skip_reason, trade_ref)
    )


def _log_journal(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, json.dumps(context) if context else None)
    )


def _get_dd_state() -> dict:
    rows = execute(f"SELECT * FROM gd_dd_state WHERE id = {DD_STATE_ID}", fetch=True)
    if rows:
        return dict(rows[0])
    execute(
        f"INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter) VALUES ({DD_STATE_ID}, 0, 0) ON CONFLICT (id) DO NOTHING"
    )
    return {"id": DD_STATE_ID, "consecutive_losses": 0, "pause_counter": 0}


def _update_dd_state(consecutive_losses: int, pause_counter: int):
    execute(
        f"UPDATE gd_dd_state SET consecutive_losses=%s, pause_counter=%s, updated_at=NOW() WHERE id={DD_STATE_ID}",
        (consecutive_losses, pause_counter)
    )


def _should_skip(dd_state: dict) -> Optional[str]:
    if dd_state["pause_counter"] > 0:
        execute(f"UPDATE gd_dd_state SET pause_counter = pause_counter - 1 WHERE id = {DD_STATE_ID}")
        return "paused_after_5_losses"
    return None


def _get_risk_multiplier(dd_state: dict, nav_usd: float) -> float:
    """Half risk after 3 consecutive losses OR if account is declining."""
    mult = 1.0
    if dd_state["consecutive_losses"] >= DD_PROTECTION["half_after_consecutive"]:
        mult = 0.5
    # Equity MA: compare live NAV against average of last 20 trade exits
    rows = execute(
        f"SELECT pnl_usd FROM gd_trades WHERE exit_time IS NOT NULL AND trade_ref LIKE '{TRADE_REF_PREFIX}%%' ORDER BY exit_time DESC LIMIT 20",
        fetch=True
    )
    if len(rows) >= 20:
        cumulative_pnl = sum(float(r["pnl_usd"] or 0) for r in rows)
        equity_20_ago = nav_usd - cumulative_pnl
        equity_ma = (equity_20_ago + nav_usd) / 2
        if nav_usd < equity_ma:
            mult *= 0.5
    return mult


def execute_signal(strategy: str, direction: str, entry_price: float, sl_price: float, tp_price: float,
                   context: dict = None, daily_pnl: float = 0):
    """
    Full Micro signal execution pipeline:
    1. Check DD filters + daily max loss
    2. Compute position size
    3. Place order on MT5/OANDA (XAU_USD)
    4. Persist trade + signal + journal to DB
    """
    trade_ref = f"{TRADE_REF_PREFIX}{uuid.uuid4().hex[:8]}"

    dd_state = _get_dd_state()

    # Daily max loss check
    if DD_PROTECTION["daily_max_loss"] and daily_pnl <= -DD_PROTECTION["daily_max_loss"]:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="daily_max_loss")
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": "daily_max_loss", "daily_pnl": daily_pnl})
        print(f"  [MICRO] Signal SKIPPED: daily_max_loss (${daily_pnl:.0f})")
        return None

    skip_reason = _should_skip(dd_state)
    if skip_reason:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=skip_reason)
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": skip_reason})
        notify.signal_skipped(strategy, direction, "XAU_USD", skip_reason)
        print(f"  [MICRO] Signal SKIPPED: {skip_reason}")
        return None

    risk_pct = STRATEGY_RISK.get(strategy, 4.0)
    acct = get_account_summary()
    if not acct or "error" in acct:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="account_summary_failed")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": "account_summary unavailable"})
        return None
    equity_usd = acct.get("nav_usd", acct.get("nav", 10000))
    risk_mult = _get_risk_multiplier(dd_state, equity_usd)

    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="zero_sl_distance")
        return None

    risk_dollar = equity_usd * (risk_pct / 100) * risk_mult
    units = int(min(risk_dollar / sl_distance, MAX_UNITS))

    if units < 1:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="units_too_small")
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": "units_too_small", "equity": equity_usd, "risk_mult": risk_mult})
        return None

    oanda_units = units if direction == "long" else -units
    print(f"  [MICRO] Placing {direction.upper()} {units} units @ market, SL={sl_price:.2f}, TP={tp_price:.2f}")

    result = place_market_order(
        instrument="XAU_USD",
        units=oanda_units,
        sl=sl_price,
        tp=tp_price,
        comment=f"{strategy}|{trade_ref}",
    )

    if not result.get("success"):
        error = result.get("error", "Unknown")
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=f"order_error: {error}")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": error})
        print(f"  [MICRO] Order FAILED: {error}")
        return None

    fill_price = result["fill_price"]
    oanda_trade_id = result["trade_id"]

    _log_signal(strategy, direction, fill_price, sl_price, tp_price, taken=True, trade_ref=trade_ref)

    execute(
        """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, units, mode, oanda_trade_id)
           VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, 'live', %s)""",
        (trade_ref, strategy, direction.upper(), fill_price, sl_price, tp_price, units, oanda_trade_id)
    )

    _log_journal(trade_ref, strategy, "ENTRY_FILLED", fill_price, {
        "instrument": "XAU_USD", "units": units, "sl": sl_price, "tp": tp_price,
        "oanda_id": oanda_trade_id, "risk_mult": risk_mult, "risk_pct": risk_pct,
        "equity_usd": equity_usd,
    })

    notify.trade_filled(trade_ref, "XAU_USD", direction, fill_price, units, sl_price, tp_price)
    print(f"  [MICRO] FILLED: {direction.upper()} {units} units @ {fill_price:.2f}, trade_id={oanda_trade_id}")
    return trade_ref


def check_open_positions():
    """Monitor open Micro positions — detect closures, enforce max hold."""
    open_db_trades = execute(
        f"SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL AND trade_ref LIKE '{TRADE_REF_PREFIX}%%'",
        fetch=True
    )

    if not open_db_trades:
        return

    oanda_open = get_open_trades()
    oanda_open_ids = {t["trade_id"] for t in oanda_open}

    for trade in open_db_trades:
        oanda_id = trade["oanda_trade_id"]

        if oanda_id in oanda_open_ids:
            if trade["entry_time"]:
                entry_time = trade["entry_time"]
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                bars_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 180
                if bars_held >= MICRO_ALPHA_SWEEP["max_bars"]:
                    print(f"  [MICRO MAX HOLD] {trade['trade_ref']} held {bars_held:.0f} bars — force closing")
                    result = close_trade(oanda_id)
                    if result.get("success"):
                        gbp_usd = _get_gbp_usd_rate()
                        realized_pl = result["realized_pl"]
                        pnl_usd = realized_pl * gbp_usd
                        execute(
                            "UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s WHERE trade_ref=%s",
                            (result["time"], result["close_price"], realized_pl, pnl_usd, "MAX_HOLD", trade["trade_ref"])
                        )
                        _update_dd_after_exit(realized_pl)
                        _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_FILLED", result["close_price"], {
                            "reason": "MAX_HOLD", "bars_held": int(bars_held), "pnl_usd": pnl_usd,
                        })
                        notify.trade_closed(trade["trade_ref"], "XAU_USD", "MAX_HOLD", realized_pl, pnl_usd)
                    else:
                        _log_journal(trade["trade_ref"], trade["strategy"], "CLOSE_FAILED", None, {
                            "reason": "MAX_HOLD", "error": result.get("error", "Unknown"),
                        })
            continue

        details = get_trade_details(oanda_id)
        if not details:
            _log_journal(trade["trade_ref"], trade["strategy"], "DETAILS_FETCH_FAILED", None, {"oanda_id": oanda_id})
            continue

        if details["state"] == "CLOSED":
            realized_pl = details["realized_pl"]
            close_time = details.get("close_time", datetime.now(timezone.utc).isoformat())
            fill_price = details.get("price", 0)

            exit_reason = "CLOSED"
            if trade["sl_price"] and abs(fill_price - float(trade["sl_price"])) < 2:
                exit_reason = "SL"
            elif trade["tp_price"] and abs(fill_price - float(trade["tp_price"])) < 2:
                exit_reason = "TP"

            gbp_usd = _get_gbp_usd_rate()
            pnl_usd = realized_pl * gbp_usd

            execute(
                """UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s
                   WHERE trade_ref=%s""",
                (close_time, fill_price, realized_pl, pnl_usd, exit_reason, trade["trade_ref"])
            )

            _update_dd_after_exit(realized_pl)
            _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_FILLED", fill_price, {
                "reason": exit_reason, "pnl_usd": pnl_usd, "oanda_id": oanda_id,
            })
            notify.trade_closed(trade["trade_ref"], "XAU_USD", exit_reason, realized_pl, pnl_usd)
            print(f"  [MICRO] CLOSED: {exit_reason} @ {fill_price:.2f}, P&L=${pnl_usd:.2f}")


def _update_dd_after_exit(realized_pl_gbp: float):
    dd_state = _get_dd_state()
    if realized_pl_gbp > 0:
        new_consecutive = 0
    else:
        new_consecutive = dd_state["consecutive_losses"] + 1
    new_pause = dd_state["pause_counter"]
    if new_consecutive >= DD_PROTECTION["consecutive_loss_pause"]:
        new_pause = DD_PROTECTION["pause_signals"]
    _update_dd_state(new_consecutive, new_pause)


def check_alpha_sweep_breakeven():
    """Check break-even for Micro trades."""
    open_trades = execute(
        f"SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL AND trade_ref LIKE '{TRADE_REF_PREFIX}%%'",
        fetch=True
    )

    if not open_trades:
        return

    price = get_current_price(instrument="XAU_USD")
    if not price:
        return

    cfg = MICRO_ALPHA_SWEEP
    for trade in open_trades:
        entry = float(trade["entry_price"])
        tp = float(trade["tp_price"]) if trade["tp_price"] else 0
        sl = float(trade["sl_price"])
        side = trade["side"]

        if tp <= 0:
            continue

        if side == "LONG":
            if tp <= entry or sl >= entry:
                continue
            target_50 = entry + (tp - entry) * cfg["be_trigger_pct"]
            if price["bid"] >= target_50:
                new_sl = entry + 0.30
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["bid"], "source": "scheduler",
                    })
                    print(f"  [MICRO] LONG break-even: SL {sl:.2f} → {new_sl:.2f}")
                else:
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                    })
        else:
            if tp >= entry or sl <= entry:
                continue
            target_50 = entry - (entry - tp) * cfg["be_trigger_pct"]
            if price["ask"] <= target_50:
                new_sl = entry - 0.30
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["ask"], "source": "scheduler",
                    })
                    print(f"  [MICRO] SHORT break-even: SL {sl:.2f} → {new_sl:.2f}")
                else:
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                    })
