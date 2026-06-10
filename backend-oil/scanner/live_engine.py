"""
Oil live trading engine — processes Alpha-Sweep signals, applies DD protection,
executes on OANDA, monitors positions. All state persisted to DB.
"""
import uuid
import json
import numpy as np
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

def _get_gbp_usd_rate():
    """Oil account is USD — no conversion needed."""
    return 1.0
from backend.db import execute, safe_json_dumps
from backend import notify
from config import STRATEGY_RISK, MAX_UNITS, ALPHA_SWEEP, slippage


def _log_signal(strategy: str, direction: str, entry: float, sl: float, tp: float,
                taken: bool, skip_reason: str = "", trade_ref: str = ""):
    execute(
        """INSERT INTO gd_signals (strategy, direction, entry_price, sl_price, tp_price, taken, skip_reason, trade_ref)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (strategy, direction, entry, sl, tp, taken, skip_reason, trade_ref)
    )


def _log_journal(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    """Insert a journal event. Context is sanitized for numpy/Decimal/datetime."""
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, safe_json_dumps(context))
    )


def _log_journal_safe(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    """Best-effort journal write — NEVER raises."""
    try:
        _log_journal(trade_ref, strategy, event_type, price, context)
    except Exception as e:
        print(f"  [OIL] _log_journal {event_type} swallowed exception: {e}")


def _get_dd_state() -> dict:
    rows = execute("SELECT * FROM gd_dd_state WHERE id = 2", fetch=True)
    if rows:
        return dict(rows[0])
    # Create Oil DD state row if missing
    execute(
        "INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity) VALUES (2, 0, 0, 5000, 5000) ON CONFLICT (id) DO NOTHING"
    )
    return {"id": 2, "consecutive_losses": 0, "pause_counter": 0, "equity": 5000, "peak_equity": 5000}


def _update_dd_state(consecutive_losses: int, pause_counter: int, equity: float, peak_equity: float):
    execute(
        """UPDATE gd_dd_state SET consecutive_losses=%s, pause_counter=%s, equity=%s, peak_equity=%s, updated_at=NOW()
           WHERE id=2""",
        (consecutive_losses, pause_counter, equity, peak_equity)
    )


def _should_skip(dd_state: dict) -> Optional[str]:
    """Check DD filters for Oil. Returns skip reason or None."""
    if dd_state["pause_counter"] > 0:
        execute("UPDATE gd_dd_state SET pause_counter = pause_counter - 1 WHERE id = 2")
        return "paused_after_5_losses"
    return None


def _get_risk_multiplier(dd_state: dict) -> float:
    mult = 1.0
    if dd_state["consecutive_losses"] >= 3:
        mult = 0.5
    rows = execute(
        "SELECT pnl_usd FROM gd_trades WHERE exit_time IS NOT NULL AND trade_ref LIKE 'OIL-%%' ORDER BY exit_time DESC LIMIT 20",
        fetch=True
    )
    if len(rows) >= 20:
        cumulative_pnl = sum(float(r["pnl_usd"] or 0) for r in rows)
        current_eq = float(dd_state["equity"])
        equity_20_ago = current_eq - cumulative_pnl
        equity_ma = (equity_20_ago + current_eq) / 2
        if current_eq < equity_ma:
            mult *= 0.5
    return mult


def execute_signal(direction: str, entry_price: float, sl_price: float, tp_price: float, context: dict = None):
    """
    Full Oil signal execution pipeline:
    1. Check DD filters
    2. Compute position size
    3. Place OANDA order (BCO_USD)
    4. Persist trade + signal + journal to DB
    """
    strategy = "alpha_sweep_oil"
    trade_ref = f"OIL-AS-{uuid.uuid4().hex[:8]}"

    dd_state = _get_dd_state()

    skip_reason = _should_skip(dd_state)
    if skip_reason:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=skip_reason)
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": skip_reason, "instrument": "BCO_USD"})
        notify.signal_skipped(strategy, direction, "BCO_USD", skip_reason)
        print(f"  [OIL] Signal SKIPPED: {skip_reason}")
        return None

    risk_mult = _get_risk_multiplier(dd_state)
    risk_pct = STRATEGY_RISK.get("alpha_sweep", 4.0)
    acct = get_account_summary()
    if "error" in acct:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="oanda_error: account_summary failed")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": "account_summary unavailable"})
        return None
    equity_usd = acct.get("nav_usd", acct.get("nav", float(dd_state["equity"])))

    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="zero_sl_distance")
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": "zero_sl_distance"})
        return None

    risk_dollar = equity_usd * (risk_pct / 100) * risk_mult
    units = int(min(risk_dollar / sl_distance, MAX_UNITS))

    if units < 1:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="units_too_small")
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": "units_too_small", "equity": equity_usd, "risk_mult": risk_mult})
        return None

    oanda_units = units if direction == "long" else -units
    print(f"  [OIL] Placing {direction.upper()} {units} barrels @ market, SL={sl_price:.4f}, TP={tp_price:.4f}")

    result = place_market_order(
        instrument="BCO_USD",
        units=oanda_units,
        sl=sl_price,
        tp=tp_price,
        comment=f"alpha_sweep_oil|{trade_ref}",
    )

    if not result.get("success"):
        error = result.get("error", "Unknown")
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=f"oanda_error: {error}")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": error, "instrument": "BCO_USD"})
        print(f"  [OIL] Order FAILED: {error}")
        return None

    fill_price = result["fill_price"]
    oanda_trade_id = result["trade_id"]

    _log_signal(strategy, direction, fill_price, sl_price, tp_price, taken=True, trade_ref=trade_ref)

    execute(
        """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
           VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)""",
        (trade_ref, strategy, direction.upper(), fill_price, sl_price, tp_price, units / 1000.0, units, oanda_trade_id)
    )

    _log_journal_safe(trade_ref, strategy, "ENTRY_FILLED", fill_price, {
        "instrument": "BCO_USD", "units": units, "sl": sl_price, "tp": tp_price,
        "oanda_id": oanda_trade_id, "risk_mult": risk_mult, "risk_pct": risk_pct,
        "equity_usd": equity_usd,
    })

    try:
        notify.trade_filled(trade_ref, "BCO_USD", direction, fill_price, units, sl_price, tp_price)
    except Exception as e:
        print(f"  [OIL] notify.trade_filled swallowed exception: {e}")
    print(f"  [OIL] FILLED: {direction.upper()} {units} barrels @ {fill_price:.4f}, trade_id={oanda_trade_id}")
    return trade_ref


def check_open_positions():
    """
    Monitor open Oil positions — detect OANDA-side closures, enforce max hold.
    """
    open_db_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL AND trade_ref LIKE 'OIL-%%'",
        fetch=True
    )

    if not open_db_trades:
        return

    oanda_open = get_open_trades()
    oanda_open_ids = {t.get("id") or t.get("trade_id") for t in oanda_open}

    for trade in open_db_trades:
        oanda_id = trade["oanda_trade_id"]

        if oanda_id in oanda_open_ids:
            # Still open — check max hold (80 M3 bars = ~4 hours)
            if trade["entry_time"]:
                entry_time = trade["entry_time"]
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                bars_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 180
                if bars_held >= ALPHA_SWEEP["max_bars"]:
                    print(f"  [OIL MAX HOLD] {trade['trade_ref']} held {bars_held:.0f} bars — force closing")
                    result = close_trade(oanda_id)
                    if result.get("success"):
                        gbp_usd = _get_gbp_usd_rate()
                        close_price = result.get("close_price", 0)
                        entry_price = float(trade["entry_price"])
                        trade_units = trade["units"] or 1
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
                        _update_dd_after_exit(realized_pl, pnl_usd)
                        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "EXIT_FILLED", result["close_price"], {
                            "reason": "MAX_HOLD", "bars_held": int(bars_held),
                            "pnl_gbp": realized_pl, "pnl_usd": pnl_usd,
                        })
                        notify.trade_closed(trade["trade_ref"], "BCO_USD", "MAX_HOLD", realized_pl, pnl_usd)
                    else:
                        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "CLOSE_FAILED", None, {
                            "reason": "MAX_HOLD", "error": result.get("error", "Unknown"),
                        })
                        notify.error(f"OIL MAX_HOLD close failed: {trade['trade_ref']}")
            continue

        # Trade not in MT5 open positions — could be closed (SL/TP/manual) OR
        # a transient DWX file race where open_orders.json briefly excluded it.
        # PREFERRED PATH: get_trade_details() reads closed_orders.json (written
        # by DWX EA's OnTradeTransaction handler with the AUTHORITATIVE broker
        # fill price + reason). If the close-record isn't there, we DO NOT
        # guess from price proximity — that's the phantom-fill bug class
        # (see docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md). We skip and retry next
        # cycle. closed_orders.json populates within ~1s of a real broker
        # close; the only legitimate way to wait this out is to retry.
        details = get_trade_details(oanda_id)

        if not details:
            # Position vanished from open_orders.json but no closed_orders.json
            # entry yet. Two possibilities:
            #   1. Real close, EA hasn't flushed closed_orders.json yet (race)
            #   2. open_orders.json was momentarily incomplete (DWX file race)
            # Either way, do NOT guess. Skip and retry next cycle.
            print(f"  [OIL] Position {oanda_id} not in open_orders, no closed_orders entry yet — "
                  f"skipping; will retry next cycle (race or pending close)")
            _log_journal(trade["trade_ref"], "alpha_sweep_oil", "EXIT_AMBIGUOUS", None, {
                "oanda_id": oanda_id,
                "reason": "no_open_no_closed_record",
            })
            continue

        if details.get("state") != "CLOSED":
            # Position is actually still open per get_trade_details — DWX
            # open_orders.json was stale when we read it. Skip and retry.
            continue

        # AUTHORITATIVE: real broker fill data
        fill_price = float(details.get("close_price", 0))
        realized_pl = float(details["realized_pl"])
        close_time = details.get("close_time", datetime.now(timezone.utc).isoformat())
        exit_reason = details.get("exit_reason", "CLOSED")

        # Defensive fallback for older closed_orders entries that didn't carry deal_reason
        if exit_reason in ("UNKNOWN", "CLOSED", None) and trade["sl_price"]:
            if abs(fill_price - float(trade["sl_price"])) < 2:
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

        _update_dd_after_exit(realized_pl, pnl_usd)

        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "EXIT_FILLED", fill_price, {
            "reason": exit_reason, "pnl_gbp": realized_pl, "pnl_usd": pnl_usd,
            "oanda_id": oanda_id, "instrument": "BCO_USD",
        })
        print(f"  [OIL] Trade {trade['trade_ref']} closed: {exit_reason} @ ${fill_price:.2f}, P&L=${pnl_usd:.2f}")
        notify.trade_closed(trade["trade_ref"], "BCO_USD", exit_reason, realized_pl, pnl_usd)


def _update_dd_after_exit(realized_pl_gbp: float, pnl_usd: float):
    """Update DD state after a trade closes."""
    dd_state = _get_dd_state()
    if realized_pl_gbp > 0:
        new_consecutive = 0
    else:
        new_consecutive = dd_state["consecutive_losses"] + 1
        if new_consecutive >= 5:
            execute("UPDATE gd_dd_state SET pause_counter = 2 WHERE id = 2")
    new_equity = float(dd_state["equity"]) + pnl_usd
    new_peak = max(float(dd_state["peak_equity"]), new_equity)
    _update_dd_state(new_consecutive, dd_state["pause_counter"], new_equity, new_peak)


def check_alpha_sweep_breakeven():
    """Scheduler fallback: check break-even for Oil trades (stream is primary)."""
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND strategy='alpha_sweep_oil' AND oanda_trade_id IS NOT NULL",
        fetch=True
    )

    if not open_trades:
        return

    price = get_current_price(instrument="BCO_USD")
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
                new_sl = entry + 0.01
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["bid"], "source": "scheduler",
                    })
                    notify.break_even(trade["trade_ref"], "BCO_USD", new_sl)
                    print(f"  [OIL] LONG break-even: SL {sl:.4f} → {new_sl:.4f}")
                else:
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                    })
        else:
            if tp >= entry:
                continue
            if sl <= entry:
                continue
            target_50 = entry - (entry - tp) * 0.5
            if price["ask"] <= target_50:
                new_sl = entry - 0.01
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["ask"], "source": "scheduler",
                    })
                    notify.break_even(trade["trade_ref"], "BCO_USD", new_sl)
                    print(f"  [OIL] SHORT break-even: SL {sl:.4f} → {new_sl:.4f}")
                else:
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                    })


def reconcile_orphans():
    """Adopt any broker positions that don't have a matching DB row.
    Production safety net for Oil Macro. See backend-oil-micro for full docs."""
    try:
        broker_open = get_open_trades(instrument="BCO_USD") or []
    except Exception as e:
        print(f"  [OIL] reconcile_orphans: get_open_trades failed: {e}")
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
        lot_size = units / 1000.0  # oil: 1 lot = 1000 barrels

        trade_ref = f"OIL-AS-orphan-{broker_id[-8:]}"

        try:
            inserted = execute(
                """INSERT INTO gd_trades (
                       trade_ref, strategy, side, entry_time, entry_price,
                       sl_price, tp_price, lot_size, units, mode, oanda_trade_id
                   )
                   VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)
                   ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING
                   RETURNING id""",
                (trade_ref, "alpha_sweep_oil", side, entry_price,
                 sl, tp, lot_size, units, broker_id),
                fetch=True
            )
        except Exception as e:
            print(f"  [OIL] reconcile_orphans: INSERT failed for {broker_id}: {e}")
            _log_journal_safe("SYSTEM", "alpha_sweep_oil", "ORPHAN_ADOPT_FAILED",
                              entry_price, {"broker_id": broker_id, "error": str(e)})
            continue

        if not inserted:
            continue

        _log_journal_safe(trade_ref, "alpha_sweep_oil", "ORPHAN_ADOPTED",
                          entry_price, {
                              "broker_id": broker_id, "side": side, "units": units,
                              "sl": sl, "tp": tp, "reason": "broker_position_not_in_db",
                          })

        try:
            notify.orphan_adopted(trade_ref, broker_id, "BCO_USD", side, units, entry_price, sl, tp)
        except Exception as e:
            print(f"  [OIL] reconcile_orphans: notify failed: {e}")

        print(f"  [OIL] ORPHAN ADOPTED: {trade_ref} (broker {broker_id}) — investigate logs")
