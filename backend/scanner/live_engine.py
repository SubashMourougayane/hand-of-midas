"""
Live trading engine — processes signals, applies DD protection, executes on OANDA.
All state persisted to DB. No in-memory state survives restarts.
"""
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.execution import (
    get_candles, get_current_price, place_market_order,
    close_trade, get_open_trades, get_account_summary, modify_stop_loss,
    get_trade_details,
)
from backend.config import EXECUTOR, STRATEGY_RISK, MAX_UNITS, ALPHA_SWEEP, MEAN_REV, CROSS_MARKET, slippage
from backend.db import execute, insert_returning, get_conn, safe_json_dumps
from backend import notify


def _get_gbp_usd_rate():
    """Get GBP/USD rate. MT5 account is USD so returns 1.0. OANDA account is GBP."""
    if EXECUTOR == "mt5":
        return 1.0
    from backend.execution.oanda_executor import _get_gbp_usd_rate as _rate
    return _rate()


def _log_signal(strategy: str, direction: str, entry: float, sl: float, tp: float, taken: bool, skip_reason: str = "", trade_ref: str = ""):
    """Persist signal to DB."""
    execute(
        """INSERT INTO gd_signals (strategy, direction, entry_price, sl_price, tp_price, taken, skip_reason, trade_ref)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (strategy, direction, entry, sl, tp, taken, skip_reason, trade_ref)
    )


def _log_journal(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    """Persist journal event. Context is sanitized for numpy/Decimal/datetime."""
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, safe_json_dumps(context))
    )


def _log_journal_safe(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    """Best-effort journal write — NEVER raises."""
    try:
        _log_journal(trade_ref, strategy, event_type, price, context)
    except Exception as e:
        print(f"  [GOLD] _log_journal {event_type} swallowed exception: {e}")


def _get_dd_state() -> dict:
    """Load DD protection state from DB."""
    rows = execute("SELECT * FROM gd_dd_state WHERE id = 1", fetch=True)
    if rows:
        return dict(rows[0])
    return {"consecutive_losses": 0, "pause_counter": 0, "equity": 5000, "peak_equity": 5000}


def _update_dd_state(consecutive_losses: int, pause_counter: int, equity: float, peak_equity: float):
    """Persist DD state to DB."""
    execute(
        """UPDATE gd_dd_state SET consecutive_losses=%s, pause_counter=%s, equity=%s, peak_equity=%s, updated_at=NOW()
           WHERE id=1""",
        (consecutive_losses, pause_counter, equity, peak_equity)
    )


def _should_skip(strategy: str, direction: str, dd_state: dict, gold_close: float = 0, gold_50ma: float = 0) -> Optional[str]:
    """Check DD filters. Returns skip reason or None."""
    # 50-MA gate
    if strategy in ("mean_rev", "cross_market") and direction == "long":
        if gold_close > 0 and gold_50ma > 0 and gold_close < gold_50ma:
            return "gold_below_50ma"

    # Pause counter
    if dd_state["pause_counter"] > 0:
        execute("UPDATE gd_dd_state SET pause_counter = pause_counter - 1 WHERE id = 1")
        return "paused_after_5_losses"

    return None


def _get_risk_multiplier(dd_state: dict) -> float:
    """Compute position size multiplier from DD state."""
    mult = 1.0
    if dd_state["consecutive_losses"] >= 3:
        mult = 0.5
    # Equity MA check: current equity vs mean of last 20 post-trade equity values
    # Use OANDA NAV as current equity proxy, compare against rolling average
    rows = execute(
        "SELECT pnl_usd FROM gd_trades WHERE exit_time IS NOT NULL ORDER BY exit_time DESC LIMIT 20",
        fetch=True
    )
    if len(rows) >= 20:
        # Reconstruct equity progression: current equity minus cumulative recent P&L gives past equity
        cumulative_pnl = sum(float(r["pnl_usd"] or 0) for r in rows)
        current_eq = float(dd_state["equity"])
        # The 20-trade MA is: average of equity at each of the last 20 trade exits
        # Approximate: current_eq - cumPnL is equity 20 trades ago, linearly interpolate
        equity_20_ago = current_eq - cumulative_pnl
        equity_ma = (equity_20_ago + current_eq) / 2  # midpoint approximation
        if current_eq < equity_ma:
            mult *= 0.5
    return mult


def _get_gold_50ma() -> tuple[float, float]:
    """Get current gold close and 50-day MA from OANDA daily candles."""
    candles = get_candles(instrument="XAU_USD", granularity="D", count=55, price="M")
    if len(candles) < 50:
        return 0, 0
    closes = [c["bid_close"] for c in candles]
    current_close = closes[-1]
    ma50 = np.mean(closes[-50:])
    return current_close, ma50


def execute_signal(strategy: str, direction: str, entry_price: float, sl_price: float, tp_price: float, context: dict = None):
    """
    Full signal execution pipeline:
    1. Check DD filters
    2. Compute position size
    3. Place OANDA order
    4. Persist trade + signal + journal to DB
    """
    trade_ref = f"GD-{strategy[:2].upper()}-{uuid.uuid4().hex[:8]}"

    # Load DD state
    dd_state = _get_dd_state()
    gold_close, gold_50ma = _get_gold_50ma()

    # DD filter check
    skip_reason = _should_skip(strategy, direction, dd_state, gold_close, gold_50ma)
    if skip_reason:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=skip_reason)
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": skip_reason})
        notify.signal_skipped(strategy, direction, "XAU_USD", skip_reason)
        print(f"  [{strategy}] Signal SKIPPED: {skip_reason}")
        return None

    # Position sizing — use USD-equivalent equity (account is GBP, gold is USD)
    risk_mult = _get_risk_multiplier(dd_state)
    risk_pct = STRATEGY_RISK.get(strategy, 3.0)
    acct = get_account_summary()
    if "error" in acct:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=f"oanda_error: account_summary failed")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": "account_summary unavailable"})
        return None
    equity_usd = acct.get("nav_usd", acct.get("nav", float(dd_state["equity"])))

    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="zero_sl_distance")
        return None

    risk_dollar = equity_usd * (risk_pct / 100) * risk_mult
    units = int(min(risk_dollar / sl_distance, MAX_UNITS))

    if units < 1:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="units_too_small")
        return None

    # Validate SL distance from current price (broker minimum stop level)
    price_now = get_current_price(instrument="XAU_USD")
    if price_now:
        current_ask = price_now["ask"]
        current_bid = price_now["bid"]
        if direction == "short" and sl_price <= current_ask + 1.0:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_too_close_to_price")
            print(f"  [{strategy}] SKIP: SL ${sl_price:.2f} too close to ask ${current_ask:.2f}")
            return None
        if direction == "long" and sl_price >= current_bid - 1.0:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_too_close_to_price")
            print(f"  [{strategy}] SKIP: SL ${sl_price:.2f} too close to bid ${current_bid:.2f}")
            return None

    # Check if there's already an open Macro position (one at a time)
    open_macro = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL AND trade_ref LIKE 'GD-AS-%%'",
        fetch=True
    )
    if open_macro and open_macro[0]["cnt"] > 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="position_already_open")
        print(f"  [{strategy}] SKIP: already have open Macro position")
        return None

    # Place order on MT5/OANDA
    oanda_units = units if direction == "long" else -units
    print(f"  [{strategy}] Placing {direction.upper()} {units} units @ market, SL={sl_price:.2f}, TP={tp_price:.2f}")

    result = place_market_order(
        instrument="XAU_USD",
        units=oanda_units,
        sl=sl_price,
        tp=tp_price if tp_price > 0 else None,
        comment=f"{strategy}|{trade_ref}",
    )

    if not result.get("success"):
        error = result.get("error", "Unknown")
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=f"oanda_error: {error}")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": error})
        print(f"  [{strategy}] Order FAILED: {error}")
        return None

    # Order filled — persist to DB (CRITICAL: wrapped in try/except)
    fill_price = result["fill_price"]
    oanda_trade_id = result["trade_id"]

    _log_signal(strategy, direction, fill_price, sl_price, tp_price, taken=True, trade_ref=trade_ref)

    try:
        execute(
            """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
               VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)""",
            (trade_ref, strategy, direction.upper(), fill_price, sl_price, tp_price, units / 100.0, units, oanda_trade_id)
        )
    except Exception as e:
        print(f"  [{strategy}] ⚠️ DB INSERT FAILED (trade is open on broker!): {e}")
        _log_journal_safe(trade_ref, strategy, "DB_INSERT_FAILED", fill_price, {"error": str(e), "oanda_id": oanda_trade_id})

    _log_journal_safe(trade_ref, strategy, "ENTRY_FILLED", fill_price, {
        "units": units, "sl": sl_price, "tp": tp_price, "oanda_id": oanda_trade_id,
        "risk_mult": risk_mult, "risk_pct": risk_pct, "equity_usd": equity_usd,
    })

    try:
        notify.trade_filled(trade_ref, "XAU_USD", direction, fill_price, units, sl_price, tp_price)
    except Exception as e:
        print(f"  [{strategy}] notify.trade_filled swallowed exception: {e}")
    print(f"  [{strategy}] FILLED: {direction.upper()} {units} units @ {fill_price:.2f}, trade_id={oanda_trade_id}")
    return trade_ref  # ALWAYS return — trade exists on broker


def check_open_positions():
    """
    Monitor open positions — check if OANDA closed them (SL/TP hit).
    Update DB for any closed trades.
    """
    # Get trades we think are open
    open_db_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL",
        fetch=True
    )

    if not open_db_trades:
        return

    # Get what OANDA says is open (all instruments — supports Gold + Oil)
    oanda_open = get_open_trades()
    oanda_open_ids = {t.get("id") or t.get("trade_id") for t in oanda_open}

    for trade in open_db_trades:
        oanda_id = trade["oanda_trade_id"]

        if oanda_id in oanda_open_ids:
            # Still open on OANDA — check max hold (hard kill after 80 bars for Alpha-Sweep)
            if trade["strategy"] == "alpha_sweep" and trade["entry_time"]:
                entry_time = trade["entry_time"]
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                bars_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 180  # M3 = 180s
                if bars_held >= 80:
                    from backend.execution import close_trade as _close
                    print(f"  [MAX HOLD] {trade['strategy']} {trade['trade_ref']} held {bars_held:.0f} bars — force closing")
                    result = _close(oanda_id)
                    if result.get("success"):
                        gbp_usd = _get_gbp_usd_rate()
                        close_price = result.get("close_price", 0)
                        entry_price = float(trade["entry_price"])
                        trade_units = trade["units"] or 1
                        # Calculate P&L from entry/exit (DWX EA doesn't return profit reliably)
                        if trade["side"] == "SHORT":
                            realized_pl = (entry_price - close_price) * trade_units
                        else:
                            realized_pl = (close_price - entry_price) * trade_units
                        pnl_usd = realized_pl * gbp_usd
                        close_time = result.get("time", datetime.now(timezone.utc).isoformat())
                        execute(
                            "UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s WHERE trade_ref=%s",
                            (close_time, close_price, realized_pl, pnl_usd, "MAX_HOLD", trade["trade_ref"])
                        )
                        dd_state = _get_dd_state()
                        new_consec = 0 if realized_pl > 0 else dd_state["consecutive_losses"] + 1
                        new_pause = 2 if new_consec >= 5 else dd_state["pause_counter"]
                        new_eq = float(dd_state["equity"]) + pnl_usd
                        _update_dd_state(new_consec, new_pause, new_eq, max(float(dd_state["peak_equity"]), new_eq))
                        _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_FILLED", result["close_price"],
                            {"reason": "MAX_HOLD", "bars_held": int(bars_held), "pnl_gbp": realized_pl, "pnl_usd": pnl_usd})
                        notify.trade_closed(trade["trade_ref"], "XAU_USD", "MAX_HOLD", realized_pl, pnl_usd)
                    else:
                        _log_journal(trade["trade_ref"], trade["strategy"], "CLOSE_FAILED", None,
                            {"reason": "MAX_HOLD", "bars_held": int(bars_held), "error": result.get("error", "Unknown")})
                        notify.error(f"MAX_HOLD close failed: {trade['trade_ref']} — {result.get('error')}")
            continue

        # Trade closed on OANDA side (SL or TP hit)
        # get_trade_details imported at top of module
        details = get_trade_details(oanda_id)

        if details and details["state"] == "CLOSED":
            realized_pl = details["realized_pl"]
            close_time = details.get("close_time", datetime.now(timezone.utc).isoformat())

            # Determine exit reason
            exit_reason = "UNKNOWN"
            fill_price = details.get("price", 0)
            if trade["sl_price"] and abs(fill_price - float(trade["sl_price"])) < 2:
                exit_reason = "SL"
            elif trade["tp_price"] and abs(fill_price - float(trade["tp_price"])) < 2:
                exit_reason = "TP"
            else:
                exit_reason = "CLOSED"

            # Update DB — OANDA returns P&L in account currency (GBP)
            # _get_gbp_usd_rate defined at top of module
            gbp_usd = _get_gbp_usd_rate()
            pnl_usd = realized_pl * gbp_usd

            execute(
                """UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s
                   WHERE trade_ref=%s""",
                (close_time, fill_price, realized_pl, pnl_usd, exit_reason, trade["trade_ref"])
            )

            # Update DD state (use USD P&L for equity tracking)
            dd_state = _get_dd_state()
            new_pause = dd_state["pause_counter"]
            if realized_pl > 0:
                new_consecutive = 0
            else:
                new_consecutive = dd_state["consecutive_losses"] + 1
                if new_consecutive >= 5:
                    new_pause = 2

            # _get_gbp_usd_rate defined at top of module
            gbp_usd_rate = _get_gbp_usd_rate()
            pnl_usd_for_equity = realized_pl * gbp_usd_rate
            new_equity = float(dd_state["equity"]) + pnl_usd_for_equity
            new_peak = max(float(dd_state["peak_equity"]), new_equity)
            _update_dd_state(new_consecutive, new_pause, new_equity, new_peak)

            _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_FILLED", fill_price, {
                "reason": exit_reason, "pnl": realized_pl, "oanda_id": oanda_id,
            })

            notify.trade_closed(trade["trade_ref"], "XAU_USD", exit_reason, realized_pl, pnl_usd)
            print(f"  [{trade['strategy']}] CLOSED: {exit_reason} @ {fill_price:.2f}, P&L=${realized_pl:.2f}")


def check_alpha_sweep_breakeven():
    """
    For open Alpha-Sweep trades, check if price reached 50% to TP.
    If so, move SL to entry (break-even).
    """
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND strategy='alpha_sweep' AND oanda_trade_id IS NOT NULL",
        fetch=True
    )

    if not open_trades:
        return

    price = get_current_price()
    if not price:
        return

    for trade in open_trades:
        entry = float(trade["entry_price"])
        tp = float(trade["tp_price"]) if trade["tp_price"] else 0
        sl = float(trade["sl_price"])
        side = trade["side"]

        if tp <= 0:
            continue

        if side == "LONG":
            if tp <= entry:
                continue
            if sl >= entry:
                continue
            target_50 = entry + (tp - entry) * 0.5
            if price["bid"] >= target_50:
                new_sl = entry + 0.30
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], "alpha_sweep", "BREAK_EVEN", new_sl, {"old_sl": sl, "trigger_price": price["bid"], "source": "scheduler"})
                    notify.break_even(trade["trade_ref"], "XAU_USD", new_sl)
                    print(f"  [alpha_sweep] LONG break-even: SL {sl:.2f} → {new_sl:.2f}")
                else:
                    _log_journal(trade["trade_ref"], "alpha_sweep", "BREAK_EVEN_FAILED", None, {"old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"), "source": "scheduler"})
        else:  # SHORT
            if tp >= entry:
                continue
            if sl <= entry:
                continue
            target_50 = entry - (entry - tp) * 0.5
            if price["ask"] <= target_50:
                new_sl = entry - 0.30
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], "alpha_sweep", "BREAK_EVEN", new_sl, {"old_sl": sl, "trigger_price": price["ask"], "source": "scheduler"})
                    notify.break_even(trade["trade_ref"], "XAU_USD", new_sl)
                    print(f"  [alpha_sweep] SHORT break-even: SL {sl:.2f} → {new_sl:.2f}")
                else:
                    _log_journal(trade["trade_ref"], "alpha_sweep", "BREAK_EVEN_FAILED", None, {"old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"), "source": "scheduler"})


def reconcile_orphans():
    """Adopt any broker positions that don't have a matching DB row.
    Production safety net for Gold Macro. Trade ref prefix is GD-."""
    try:
        broker_open = get_open_trades(instrument="XAU_USD") or []
    except Exception as e:
        print(f"  [GOLD] reconcile_orphans: get_open_trades failed: {e}")
        return

    if not broker_open:
        return

    # Look up ANY system's open positions — see backend-oil-micro for full
    # rationale. June 11: cross-system pollution caused Telegram spam.
    db_open_rows = execute(
        "SELECT oanda_trade_id FROM gd_trades "
        "WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL",
        fetch=True
    )
    db_open_ids = {str(r["oanda_trade_id"]) for r in (db_open_rows or [])}

    for pos in broker_open:
        broker_id = str(pos.get("id") or pos.get("trade_id") or "")
        if not broker_id or broker_id in db_open_ids:
            continue

        units_signed = pos.get("currentUnits", 0)
        units = abs(int(units_signed))
        side = "LONG" if units_signed > 0 else "SHORT"
        entry_price = float(pos.get("price", 0))
        sl = float(pos.get("sl") or 0)
        tp = float(pos.get("tp") or 0)
        lot_size = units / 100.0  # gold: 1 lot = 100 oz

        trade_ref = f"GD-AL-orphan-{broker_id[-8:]}"

        try:
            inserted = execute(
                """INSERT INTO gd_trades (
                       trade_ref, strategy, side, entry_time, entry_price,
                       sl_price, tp_price, lot_size, units, mode, oanda_trade_id
                   )
                   VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)
                   ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING
                   RETURNING id""",
                (trade_ref, "alpha_sweep", side, entry_price,
                 sl, tp, lot_size, units, broker_id),
                fetch=True
            )
        except Exception as e:
            print(f"  [GOLD] reconcile_orphans: INSERT failed for {broker_id}: {e}")
            _log_journal_safe("SYSTEM", "alpha_sweep", "ORPHAN_ADOPT_FAILED",
                              entry_price, {"broker_id": broker_id, "error": str(e)})
            continue

        if not inserted:
            continue

        _log_journal_safe(trade_ref, "alpha_sweep", "ORPHAN_ADOPTED",
                          entry_price, {
                              "broker_id": broker_id, "side": side, "units": units,
                              "sl": sl, "tp": tp, "reason": "broker_position_not_in_db",
                          })

        try:
            notify.orphan_adopted(trade_ref, broker_id, "XAU_USD", side, units, entry_price, sl, tp)
        except Exception as e:
            print(f"  [GOLD] reconcile_orphans: notify failed: {e}")

        print(f"  [GOLD] ORPHAN ADOPTED: {trade_ref} (broker {broker_id}) — investigate logs")
