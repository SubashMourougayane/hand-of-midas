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
    get_current_price, place_market_order, place_limit_order,
    cancel_pending_order,
    close_trade, get_open_trades, get_account_summary,
    modify_stop_loss, get_trade_details,
)
from backend.db import execute, safe_json_dumps
from backend import notify
from config import STRATEGY_RISK, MAX_UNITS, MICRO_ALPHA_SWEEP, DD_STATE_ID, TRADE_REF_PREFIX, DD_PROTECTION
from backend.execution.limit_price import compute_limit_price, parse_dry_run_env
from scanner import _log

# Price extremes cache: tracks HIGH and LOW seen per open trade.
# When a trade disappears from MT5, we check if price reached SL or TP level.
# If high >= SL (for SHORT) → SL was hit. If low <= TP (for SHORT) → TP was hit.
# If BOTH reached → default to SL (conservative). If NEITHER → SL (impossible but safe).
_price_extremes = {}  # {oanda_trade_id: {"high": float, "low": float}}

# Per-trade MAX_HOLD market-closed defer state. See backend/scanner/live_engine.py.
_max_hold_deferred: dict = {}
_MARKET_CLOSED_HINTS = ("market closed", "market is closed", "trade is disabled", "trade disabled")
_MARKET_CLOSED_RETCODES = {10018}


def _is_market_closed_error(result: dict) -> bool:
    if not result:
        return False
    err = (result.get("error") or "").lower()
    if any(hint in err for hint in _MARKET_CLOSED_HINTS):
        return True
    return result.get("retcode") in _MARKET_CLOSED_RETCODES


def _get_gbp_usd_rate():
    from backend.config import EXECUTOR
    if EXECUTOR == "mt5":
        return 1.0
    from backend.execution.oanda_executor import _get_gbp_usd_rate as _rate
    return _rate()


def _compute_tick_age_secs(tick_time_str: str) -> Optional[float]:
    """Bug #1 (Jun 18) diagnostic: how stale is the tick we just read?

    DWX EA writes market_data.json with `time` field as MT5 server time
    string ("2026.06.18 15:18:14"). Compute clock-side delta to detect
    stale ticks. See docs/30-day-challenge/ideas/IDEAS.md "PHANTOM BE arm".
    """
    if not tick_time_str:
        return None
    try:
        tick_dt = datetime.strptime(tick_time_str, "%Y.%m.%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    delta = (datetime.now() - tick_dt).total_seconds()
    return round(delta, 1)


def _log_signal(strategy: str, direction: str, entry: float, sl: float, tp: float,
                taken: bool, skip_reason: str = "", trade_ref: str = ""):
    execute(
        """INSERT INTO gd_signals (strategy, direction, entry_price, sl_price, tp_price, taken, skip_reason, trade_ref)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (strategy, direction, entry, sl, tp, taken, skip_reason, trade_ref)
    )


def _log_journal(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    """Insert a journal event. Context is sanitized for numpy/Decimal/datetime
    so json.dumps can never crash on unexpected types."""
    execute(
        "INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context) VALUES (%s, %s, %s, %s, %s)",
        (trade_ref, strategy, event_type, price, safe_json_dumps(context))
    )


def _log_journal_safe(trade_ref: str, strategy: str, event_type: str, price: float = None, context: dict = None):
    """Best-effort journal write — NEVER raises.
    Issue #15 fix 2026-06-15: also emit structured _log.exception.
    """
    try:
        _log_journal(trade_ref, strategy, event_type, price, context)
    except Exception as e:
        try:
            _log.exception("JOURNAL", "log_journal_failed",
                           trade_ref=trade_ref, event_type=event_type, err=str(e))
        except Exception:
            pass
        print(f"  [MICRO] _log_journal {event_type} swallowed exception: {e}")


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
    # Issue #6 fix 2026-06-15: prior `or` chain fell back to hardcoded 10000
    # silently if nav_usd/nav/balance were all 0 (e.g., margin event, broker
    # reconnect storm). That could size a position 5x larger than reality.
    # Now: prefer dd_state.equity (tracked) as fallback; sanity-floor at $100.
    equity_usd = acct.get("nav_usd") or acct.get("nav") or acct.get("balance") or float(dd_state["equity"])
    if equity_usd is None or equity_usd < 100:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="equity_too_low")
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": "equity_too_low", "equity": equity_usd})
        print(f"  [MICRO] SKIP: equity ${equity_usd} below $100 floor — refusing to size trade")
        return None
    risk_mult = _get_risk_multiplier(dd_state, equity_usd)

    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="zero_sl_distance")
        return None

    risk_dollar = equity_usd * (risk_pct / 100) * risk_mult
    units_raw = risk_dollar / sl_distance
    units_capped = min(units_raw, MAX_UNITS)
    units = int(units_capped)
    # DIAG (2026-06-12): GD-MI-09314bdd showed units=38 when formula yields 15.
    # Log every input so next trade pinpoints the discrepancy. NO behavior change.
    print(f"  [MICRO][SIZE-DIAG] entry={entry_price:.4f} sl={sl_price:.4f} sl_dist={sl_distance:.4f} "
          f"equity={equity_usd:.2f} risk_pct={risk_pct} risk_mult={risk_mult} "
          f"risk_dollar={risk_dollar:.2f} MAX_UNITS={MAX_UNITS} "
          f"units_raw={units_raw:.4f} units_capped={units_capped:.4f} units_final={units}")

    if units < 1:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="units_too_small")
        _log_journal(trade_ref, strategy, "SIGNAL_SKIPPED", entry_price, {"reason": "units_too_small", "equity": equity_usd, "risk_mult": risk_mult})
        return None

    # Reject if SL is 0 or None (must always have server-side protection)
    if not sl_price or sl_price <= 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_is_zero")
        print(f"  [MICRO] SKIP: SL is {sl_price} — every trade MUST have SL")
        return None

    # Validate SL distance from current price (broker minimum stop level)
    price_now = get_current_price(instrument="XAU_USD")
    if price_now:
        current_ask = price_now["ask"]
        current_bid = price_now["bid"]
        if direction == "short" and sl_price <= current_ask + 1.0:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_too_close_to_price")
            print(f"  [MICRO] SKIP: SL ${sl_price:.2f} too close to ask ${current_ask:.2f} (need >$1 gap)")
            return None
        if direction == "long" and sl_price >= current_bid - 1.0:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_too_close_to_price")
            print(f"  [MICRO] SKIP: SL ${sl_price:.2f} too close to bid ${current_bid:.2f} (need >$1 gap)")
            return None

    # Validate TP is on profitable side (catches stale signals where price moved past TP)
    if price_now:
        if direction == "long" and tp_price <= price_now["ask"] + 1.0:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="tp_already_passed")
            print(f"  [MICRO] SKIP: LONG TP ${tp_price:.2f} <= ask ${price_now['ask']:.2f} (price already past TP)")
            return None
        if direction == "short" and tp_price >= price_now["bid"] - 1.0:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="tp_already_passed")
            print(f"  [MICRO] SKIP: SHORT TP ${tp_price:.2f} >= bid ${price_now['bid']:.2f} (price already past TP)")
            return None

    # Defense-in-depth: open-position guard at execute_signal layer.
    # Scheduler also checks, but if a future caller bypasses scheduler
    # (orphan adoption, manual injection, refactor), this stops duplicates.
    # Same pattern as Gold Macro fix 2026-06-15.
    open_micro = execute(
        f"SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND exit_time IS NULL",
        fetch=True
    )
    if open_micro and open_micro[0]["cnt"] > 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="position_already_open")
        print(f"  [MICRO] SKIP: already have open Micro position")
        return None

    oanda_units = units if direction == "long" else -units

    # Filter #27: limit-order entry path. Mirrors Oil Macro at
    # backend-oil/scanner/live_engine.py (canonical implementation).
    cfg_entry_mode = MICRO_ALPHA_SWEEP.get("entry_mode", "market")
    # M2 (2026-06-17): log resolved entry_mode so config typos are visible.
    will_use_limit = (cfg_entry_mode == "limit")
    _log.info("BROKER", "entry_mode_resolved",
              raw=cfg_entry_mode, will_use_limit=will_use_limit, trade_ref=trade_ref)
    if cfg_entry_mode == "limit":
        limit_offset_pct = MICRO_ALPHA_SWEEP.get("limit_offset_pct", 0.0)
        limit_ttl_bars = MICRO_ALPHA_SWEEP.get("limit_ttl_bars", 5)
        ttl_seconds = limit_ttl_bars * 180  # M3 = 180s/bar
        risk_distance = abs(entry_price - sl_price)
        live_price = get_current_price("XAU_USD")
        engulf_ask = live_price["ask"] if live_price else entry_price
        engulf_bid = live_price["bid"] if live_price else entry_price
        try:
            intended_limit = compute_limit_price(
                direction=direction,
                signal_entry=entry_price,
                signal_risk=risk_distance,
                engulf_close_ask=engulf_ask,
                engulf_close_bid=engulf_bid,
                limit_offset_pct=limit_offset_pct,
            )
        except Exception as e:
            _log.exception("BROKER", "compute_limit_price_failed", trade_ref=trade_ref, err=str(e))
            intended_limit = None
            # M3 (2026-06-17): journal the limit→market fall-back. See backend-oil canonical.
            _log_journal_safe(trade_ref, strategy, "LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET",
                              entry_price, {
                                  "instrument": "XAU_USD",
                                  "error": str(e),
                                  "entry_price": entry_price,
                                  "sl_price": sl_price,
                                  "tp_price": tp_price,
                                  "offset_pct": str(limit_offset_pct),
                                  "fallback_action": "market_order",
                              })

        # Default ON: dry-run unless operator explicitly opts out.
        # H1 + M7 (2026-06-17): parse_dry_run_env with per-system override.
        # MICRO_LIMIT_DRY_RUN wins, falls back to global LIMIT_DRY_RUN.
        dry_run = parse_dry_run_env(system_prefix="MICRO")

        if intended_limit is not None:
            # H6 (2026-06-17): through-market check. Refuse to place a limit
            # clearly through current market (LONG: limit > ask, SHORT: limit < bid).
            # Permissive thresholds preserve between-bid-ask placements which
            # work in production. See docs/FILTER_27_AUDIT_BACKLOG.md H6.
            if live_price:
                live_bid_now = live_price.get("bid")
                live_ask_now = live_price.get("ask")
                if direction == "long" and live_ask_now and intended_limit > live_ask_now:
                    _log.error("BROKER", "limit_price_through_market_long",
                               trade_ref=trade_ref, intended_limit=intended_limit,
                               current_ask=live_ask_now, current_bid=live_bid_now,
                               distance=intended_limit - live_ask_now)
                    _log_journal_safe(trade_ref, strategy, "LIMIT_PRICE_THROUGH_MARKET",
                                      intended_limit, {
                                          "instrument": "XAU_USD",
                                          "side": "long",
                                          "intended_limit": intended_limit,
                                          "current_ask": live_ask_now,
                                          "current_bid": live_bid_now,
                                          "distance_through_ask": intended_limit - live_ask_now,
                                          "reason": "limit_above_current_ask_for_long",
                                      })
                    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                                taken=False, skip_reason="limit_price_through_market")
                    return None
                if direction == "short" and live_bid_now and intended_limit < live_bid_now:
                    _log.error("BROKER", "limit_price_through_market_short",
                               trade_ref=trade_ref, intended_limit=intended_limit,
                               current_bid=live_bid_now, current_ask=live_ask_now,
                               distance=live_bid_now - intended_limit)
                    _log_journal_safe(trade_ref, strategy, "LIMIT_PRICE_THROUGH_MARKET",
                                      intended_limit, {
                                          "instrument": "XAU_USD",
                                          "side": "short",
                                          "intended_limit": intended_limit,
                                          "current_bid": live_bid_now,
                                          "current_ask": live_ask_now,
                                          "distance_through_bid": live_bid_now - intended_limit,
                                          "reason": "limit_below_current_bid_for_short",
                                      })
                    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                                taken=False, skip_reason="limit_price_through_market")
                    return None

            # C2: defense-in-depth — refuse to place a limit where SL is on the
            # wrong side. Math should guarantee this for current variants
            # (LONG: limit=entry+offset×risk with offset≤0 → sl=entry−risk < limit;
            #  SHORT: mirror), but a future variant sweep or sl_price formula
            # change could regress it. Production has 0 wrong-side hits today
            # (verified 2026-06-17). See docs/FILTER_27_AUDIT_BACKLOG.md C2.
            if direction == "long" and sl_price >= intended_limit:
                _log.error("BROKER", "limit_invalid_sl_long",
                           trade_ref=trade_ref, intended_limit=intended_limit,
                           sl_price=sl_price, gap=sl_price - intended_limit)
                _log_journal_safe(trade_ref, strategy, "LIMIT_INVALID_SL",
                                  intended_limit, {
                                      "instrument": "XAU_USD",
                                      "side": "long",
                                      "sl": sl_price,
                                      "intended_limit": intended_limit,
                                      "reason": "sl_above_or_equal_long_limit",
                                  })
                _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                            taken=False, skip_reason="limit_invalid_sl_wrong_side")
                return None
            if direction == "short" and sl_price <= intended_limit:
                _log.error("BROKER", "limit_invalid_sl_short",
                           trade_ref=trade_ref, intended_limit=intended_limit,
                           sl_price=sl_price, gap=intended_limit - sl_price)
                _log_journal_safe(trade_ref, strategy, "LIMIT_INVALID_SL",
                                  intended_limit, {
                                      "instrument": "XAU_USD",
                                      "side": "short",
                                      "sl": sl_price,
                                      "intended_limit": intended_limit,
                                      "reason": "sl_below_or_equal_short_limit",
                                  })
                _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                            taken=False, skip_reason="limit_invalid_sl_wrong_side")
                return None

            _log.info("BROKER", "limit_intent_computed",
                      direction=direction, intended_limit=intended_limit,
                      entry_price=entry_price, sl_price=sl_price, risk=risk_distance,
                      offset_pct=str(limit_offset_pct), ttl_seconds=ttl_seconds,
                      dry_run=dry_run, trade_ref=trade_ref)
            _log_journal_safe(trade_ref, strategy, "LIMIT_DRY_RUN_INTENT", intended_limit, {
                "instrument": "XAU_USD",
                "intended_limit": intended_limit,
                "entry_price": entry_price,
                "ttl_seconds": ttl_seconds,
                "offset_pct": str(limit_offset_pct),
                "dry_run": dry_run,
                "actual_path": "market_order" if dry_run else "limit_order_pending",
            })

            if not dry_run:
                # REAL LIMIT PATH
                _log.info("BROKER", "limit_order_placing", direction=direction,
                          units=units, limit_price=intended_limit, sl=sl_price,
                          tp=tp_price, ttl_seconds=ttl_seconds, trade_ref=trade_ref)
                print(f"  [MICRO] Placing {direction.upper()} {units} units @ LIMIT "
                      f"${intended_limit:.2f}, SL={sl_price:.2f}, TP={tp_price:.2f}, "
                      f"TTL={ttl_seconds}s")
                limit_result = place_limit_order(
                    instrument="XAU_USD",
                    units=oanda_units,
                    limit_price=intended_limit,
                    sl=sl_price,
                    tp=tp_price,
                    ttl_seconds=ttl_seconds,
                    comment=f"{strategy}|{trade_ref}",
                )
                if not limit_result.get("success"):
                    error = limit_result.get("error", "Unknown")
                    _log.error("BROKER", "limit_order_failed", direction=direction,
                               units=units, err=error, trade_ref=trade_ref)
                    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                                taken=False, skip_reason=f"limit_order_error: {error}")
                    _log_journal(trade_ref, strategy, "LIMIT_ORDER_FAILED", entry_price,
                                 {"error": error, "instrument": "XAU_USD",
                                  "intended_limit": intended_limit})
                    print(f"  [MICRO] Limit order FAILED: {error}")
                    return None

                pending_ticket = limit_result["ticket"]
                _log.info("BROKER", "limit_order_placed", direction=direction,
                          units=units, limit_price=limit_result.get("limit_price", intended_limit),
                          ticket=pending_ticket, expiration=limit_result.get("expiration_time"),
                          trade_ref=trade_ref)
                try:
                    execute(
                        """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time,
                           entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
                           VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'pending', %s)""",
                        (trade_ref, strategy, direction.upper(), intended_limit, sl_price,
                         tp_price, units / 100.0, units, pending_ticket)
                    )
                except Exception as e:
                    _log.exception("DB", "pending_insert_failed_orphan_risk",
                                   trade_ref=trade_ref, oanda_id=pending_ticket,
                                   limit_price=intended_limit, err=str(e))
                    print(f"  [MICRO] DB INSERT FAILED (limit is pending on broker!): {e}")
                    try:
                        _log_journal(trade_ref, strategy, "DB_INSERT_FAILED",
                                     intended_limit, {"error": str(e),
                                                       "oanda_id": pending_ticket,
                                                       "kind": "pending"})
                    except Exception:
                        pass

                _log_journal_safe(trade_ref, strategy, "LIMIT_PLACED", intended_limit, {
                    "instrument": "XAU_USD", "units": units, "sl": sl_price, "tp": tp_price,
                    "ticket": pending_ticket, "ttl_seconds": ttl_seconds,
                    "expiration": limit_result.get("expiration_time"),
                    "risk_dollar": risk_dollar, "equity_usd": equity_usd,
                })
                try:
                    notify.limit_placed(trade_ref, "XAU_USD", direction,
                                        intended_limit, ttl_seconds)
                except Exception as e:
                    print(f"  [MICRO] notify.limit_placed swallowed exception: {e}")
                # M11: limit-success path missing _log_signal(taken=True) →
                # broken 5-min cooldown gate. Fix: write the cooldown row.
                # Wrap in try/except: broker order already on the wire.
                try:
                    _log_signal(strategy, direction, intended_limit, sl_price,
                                tp_price, taken=True, trade_ref=trade_ref)
                except Exception as e:
                    print(f"  [MICRO] _log_signal FAILED (limit path): {e}")
                print(f"  [MICRO] LIMIT PLACED: ticket={pending_ticket} @ ${intended_limit:.2f}")
                return trade_ref

    _log.info("BROKER", "order_placing", direction=direction, units=units, sl=sl_price, tp=tp_price, trade_ref=trade_ref, units_raw=units_raw, risk_dollar=risk_dollar, equity_usd=equity_usd)
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
        _log.error("BROKER", "order_failed", direction=direction, units=units, err=error, trade_ref=trade_ref)
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=f"order_error: {error}")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": error})
        print(f"  [MICRO] Order FAILED: {error}")
        return None

    fill_price = result["fill_price"]
    oanda_trade_id = result["trade_id"]
    _log.info("BROKER", "order_filled", direction=direction, units=units, fill=fill_price, oanda_id=oanda_trade_id, trade_ref=trade_ref)

    # ALL DB operations after fill are in try/except — trade exists on MT5 regardless
    # Must ALWAYS return trade_ref to prevent duplicate orders
    try:
        _log_signal(strategy, direction, fill_price, sl_price, tp_price, taken=True, trade_ref=trade_ref)
    except Exception as e:
        _log.exception("DB", "log_signal_failed", trade_ref=trade_ref, err=str(e))
        print(f"  [MICRO] ⚠️ _log_signal FAILED: {e}")

    try:
        execute(
            """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
               VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)""",
            (trade_ref, strategy, direction.upper(), fill_price, sl_price, tp_price, units / 100.0, units, oanda_trade_id)
        )
    except Exception as e:
        _log.exception("DB", "trade_insert_failed_orphan_risk", trade_ref=trade_ref, oanda_id=oanda_trade_id, fill=fill_price, err=str(e))
        print(f"  [MICRO] ⚠️ DB INSERT FAILED (trade is open on MT5!): {e}")
        try:
            _log_journal(trade_ref, strategy, "DB_INSERT_FAILED", fill_price, {"error": str(e), "oanda_id": oanda_trade_id})
        except:
            pass

    _log_journal_safe(trade_ref, strategy, "ENTRY_FILLED", fill_price, {
        "instrument": "XAU_USD", "units": units, "sl": sl_price, "tp": tp_price,
        "oanda_id": oanda_trade_id, "risk_mult": risk_mult, "risk_pct": risk_pct,
        "equity_usd": equity_usd,
        # DIAG fields (2026-06-12 over-sizing investigation)
        "size_diag": {
            "entry_calc": entry_price, "sl_calc": sl_price, "sl_distance": sl_distance,
            "risk_dollar": risk_dollar, "max_units_cap": MAX_UNITS,
            "units_raw": units_raw, "units_capped": units_capped, "units_final": units,
        },
    })

    try:
        notify.trade_filled(trade_ref, "XAU_USD", direction, fill_price, units, sl_price, tp_price)
    except Exception as e:
        print(f"  [MICRO] notify.trade_filled swallowed exception: {e}")
    print(f"  [MICRO] FILLED: {direction.upper()} {units} units @ {fill_price:.2f}, trade_id={oanda_trade_id}")
    return trade_ref  # ALWAYS return — trade exists on broker regardless of DB state


def check_open_positions():
    """Monitor open Micro positions — detect closures, enforce max hold."""
    global _price_extremes
    # Filter #27: exclude pending limits — see backend-oil/scanner/live_engine.py
    # for canonical comment.
    open_db_trades = execute(
        f"SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL "
        f"AND trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )

    _log.debug("POSITION", "tick", open=len(open_db_trades) if open_db_trades else 0)
    if not open_db_trades:
        return

    oanda_open = get_open_trades()
    oanda_open_ids = {t.get("id") or t.get("trade_id") for t in oanda_open}

    # Track price extremes for all open trades (high/low seen during trade life).
    # Used to determine SL vs TP when trade disappears from MT5.
    price_now = get_current_price(instrument="XAU_USD")
    if price_now:
        for trade in open_db_trades:
            oid = trade["oanda_trade_id"]
            if oid in oanda_open_ids:
                mid = (price_now["bid"] + price_now["ask"]) / 2
                if oid not in _price_extremes:
                    _price_extremes[oid] = {"high": mid, "low": mid}
                else:
                    _price_extremes[oid]["high"] = max(_price_extremes[oid]["high"], mid)
                    _price_extremes[oid]["low"] = min(_price_extremes[oid]["low"], mid)
                _log.debug("POSITION", "state", ref=trade["trade_ref"], side=trade["side"], entry=float(trade["entry_price"]), sl=float(trade["sl_price"] or 0), tp=float(trade["tp_price"] or 0), current=mid, mae=_price_extremes[oid]["low"] if trade["side"]=="LONG" else _price_extremes[oid]["high"], mfe=_price_extremes[oid]["high"] if trade["side"]=="LONG" else _price_extremes[oid]["low"])

    for trade in open_db_trades:
        oanda_id = trade["oanda_trade_id"]

        if oanda_id in oanda_open_ids:
            if trade["entry_time"]:
                entry_time = trade["entry_time"]
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                bars_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 180
                if bars_held >= MICRO_ALPHA_SWEEP["max_bars"]:
                    _log.info("EXIT", "max_hold_force_close", ref=trade["trade_ref"], bars_held=int(bars_held), max_bars=MICRO_ALPHA_SWEEP["max_bars"], oanda_id=oanda_id)
                    print(f"  [MICRO MAX HOLD] {trade['trade_ref']} held {bars_held:.0f} bars — force closing")
                    result = close_trade(oanda_id)
                    if result.get("success"):
                        was_deferred = _max_hold_deferred.pop(oanda_id, False)
                        exit_reason = "MAX_HOLD (deferred)" if was_deferred else "MAX_HOLD"
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
                            (close_time, close_price, realized_pl, pnl_usd, exit_reason, trade["trade_ref"])
                        )
                        _update_dd_after_exit(realized_pl)
                        _log.info("EXIT", "detected", ref=trade["trade_ref"], reason=exit_reason, fill=close_price, pnl_usd=pnl_usd, bars_held=int(bars_held), source="max_hold")
                        _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_FILLED", result["close_price"], {
                            "reason": exit_reason, "bars_held": int(bars_held), "pnl_usd": pnl_usd,
                        })
                        notify.trade_closed(trade["trade_ref"], "XAU_USD", exit_reason, realized_pl, pnl_usd)
                    elif _is_market_closed_error(result):
                        already_notified = _max_hold_deferred.get(oanda_id, False)
                        _max_hold_deferred[oanda_id] = True
                        _log.warn("EXIT", "max_hold_deferred", ref=trade["trade_ref"], oanda_id=oanda_id,
                            bars_held=int(bars_held), error=result.get("error"), retcode=result.get("retcode"),
                            first_notify=not already_notified)
                        if not already_notified:
                            _log_journal(trade["trade_ref"], trade["strategy"], "MAX_HOLD_DEFERRED", None, {
                                "reason": "market_closed", "bars_held": int(bars_held),
                                "error": result.get("error"), "retcode": result.get("retcode"),
                            })
                            notify.max_hold_deferred(trade["trade_ref"], "XAU_USD")
                    else:
                        _log.error("BROKER", "max_hold_close_failed", ref=trade["trade_ref"], oanda_id=oanda_id, err=result.get("error", "Unknown"))
                        _log_journal(trade["trade_ref"], trade["strategy"], "CLOSE_FAILED", None, {
                            "reason": "MAX_HOLD", "error": result.get("error", "Unknown"),
                        })
            continue

        # Trade not in MT5 open positions — it was closed (SL/TP hit or manual).
        # PREFERRED PATH: get_trade_details() reads closed_orders.json (written by
        # DWX EA's OnTradeTransaction handler with the AUTHORITATIVE broker fill
        # price + reason). The old heuristic-on-extremes fallback is kept ONLY for
        # the case where the closed-orders file is missing or the trade isn't in
        # it yet (race condition). See docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md.
        details = get_trade_details(oanda_id)
        exit_reason = None  # set explicitly below in each branch

        if details and details.get("state") == "CLOSED":
            # AUTHORITATIVE: real broker fill data
            _price_extremes.pop(oanda_id, None)
            realized_pl = float(details["realized_pl"])
            close_time = details.get("close_time", datetime.now(timezone.utc).isoformat())
            fill_price = float(details.get("close_price", 0))
            exit_reason = details.get("exit_reason", "CLOSED")
            print(f"  [MICRO] Position {oanda_id} CLOSED via broker history — "
                  f"reason={exit_reason} fill={fill_price:.2f} pnl=${realized_pl:.2f}")
        elif not details:
            # Fallback: position gone from open_orders.json AND not yet in
            # closed_orders.json. Use price-extreme heuristic but flag the
            # ambiguity. This path produced wrong P&L on June 10 — see bug doc.
            sl_price = float(trade["sl_price"]) if trade["sl_price"] else 0
            tp_price = float(trade["tp_price"]) if trade["tp_price"] else 0
            entry_price = float(trade["entry_price"])
            units = trade["units"] or 1
            extremes = _price_extremes.pop(oanda_id, None)

            if trade["side"] == "SHORT":
                sl_reached = extremes and extremes["high"] >= sl_price if sl_price else False
                tp_reached = extremes and extremes["low"] <= tp_price if tp_price else False
                if tp_reached and not sl_reached:
                    fill_price = tp_price
                    realized_pl = (entry_price - tp_price) * units
                    exit_reason = "TP"
                elif sl_reached and not tp_reached:
                    fill_price = sl_price
                    realized_pl = (entry_price - sl_price) * units
                    exit_reason = "SL"
                else:
                    # AMBIGUOUS (both or neither). Don't guess — flag and skip.
                    # Next monitor cycle will retry; closed_orders.json should
                    # populate within ~1 second of the broker close.
                    print(f"  [MICRO] Position {oanda_id} closed but reason AMBIGUOUS "
                          f"(both={sl_reached and tp_reached}, neither={not sl_reached and not tp_reached}). "
                          f"Skipping — will retry next cycle when closed_orders.json populates.")
                    _log.warn("EXIT", "ambiguous", trade_ref=trade["trade_ref"], oanda_id=oanda_id, sl_reached=bool(sl_reached), tp_reached=bool(tp_reached), extremes=extremes)
                    _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_AMBIGUOUS", None, {
                        "oanda_id": oanda_id, "sl_reached": bool(sl_reached), "tp_reached": bool(tp_reached),
                        "extremes": extremes,
                    })
                    # Put extremes BACK so we can retry next cycle
                    if extremes:
                        _price_extremes[oanda_id] = extremes
                    continue
            else:
                sl_reached = extremes and extremes["low"] <= sl_price if sl_price else False
                tp_reached = extremes and extremes["high"] >= tp_price if tp_price else False
                if tp_reached and not sl_reached:
                    fill_price = tp_price
                    realized_pl = (tp_price - entry_price) * units
                    exit_reason = "TP"
                elif sl_reached and not tp_reached:
                    fill_price = sl_price
                    realized_pl = (sl_price - entry_price) * units
                    exit_reason = "SL"
                else:
                    print(f"  [MICRO] Position {oanda_id} closed but reason AMBIGUOUS "
                          f"(both={sl_reached and tp_reached}, neither={not sl_reached and not tp_reached}). "
                          f"Skipping — will retry next cycle when closed_orders.json populates.")
                    _log.warn("EXIT", "ambiguous", trade_ref=trade["trade_ref"], oanda_id=oanda_id, sl_reached=bool(sl_reached), tp_reached=bool(tp_reached), extremes=extremes)
                    _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_AMBIGUOUS", None, {
                        "oanda_id": oanda_id, "sl_reached": bool(sl_reached), "tp_reached": bool(tp_reached),
                        "extremes": extremes,
                    })
                    if extremes:
                        _price_extremes[oanda_id] = extremes
                    continue

            close_time = datetime.now(timezone.utc).isoformat()
            ext_str = f"high={extremes['high']:.2f}, low={extremes['low']:.2f}" if extremes else "no data"
            print(f"  [MICRO] Position {oanda_id} closed (heuristic, no closed_orders entry yet) — "
                  f"reason={exit_reason} fill={fill_price:.2f} extremes=({ext_str})")
        else:
            continue  # Still open somehow

        # If exit_reason wasn't explicitly set (fallback shouldn't reach here, but defense):
        if exit_reason is None or exit_reason == "CLOSED":
            if trade["sl_price"] and abs(fill_price - float(trade["sl_price"])) < 2:
                exit_reason = "SL"
            elif trade["tp_price"] and abs(fill_price - float(trade["tp_price"])) < 2:
                exit_reason = "TP"
            else:
                exit_reason = exit_reason or "CLOSED"

        gbp_usd = _get_gbp_usd_rate()
        pnl_usd = realized_pl * gbp_usd

        execute(
            """UPDATE gd_trades SET exit_time=%s, exit_price=%s, pnl_gbp=%s, pnl_usd=%s, exit_reason=%s
               WHERE trade_ref=%s""",
            (close_time, fill_price, realized_pl, pnl_usd, exit_reason, trade["trade_ref"])
        )

        _update_dd_after_exit(realized_pl)
        _log.info("EXIT", "detected", trade_ref=trade["trade_ref"], reason=exit_reason, fill=fill_price, pnl_usd=pnl_usd, oanda_id=oanda_id)
        _log_journal(trade["trade_ref"], trade["strategy"], "EXIT_FILLED", fill_price, {
            "reason": exit_reason, "pnl_usd": pnl_usd, "oanda_id": oanda_id,
        })
        notify.trade_closed(trade["trade_ref"], "XAU_USD", exit_reason, realized_pl, pnl_usd)
        print(f"  [MICRO] CLOSED: {exit_reason} @ {fill_price:.2f}, P&L=${pnl_usd:.2f}")


def _update_dd_after_exit(realized_pl_gbp: float):
    dd_state = _get_dd_state()
    old_consecutive = dd_state["consecutive_losses"]
    old_pause = dd_state["pause_counter"]
    if realized_pl_gbp > 0:
        new_consecutive = 0
    else:
        new_consecutive = dd_state["consecutive_losses"] + 1
    new_pause = dd_state["pause_counter"]
    if new_consecutive >= DD_PROTECTION["consecutive_loss_pause"]:
        new_pause = DD_PROTECTION["pause_signals"]
    _log.info("SYSTEM", "dd_state_update", pl=realized_pl_gbp, consec_old=old_consecutive, consec_new=new_consecutive, pause_old=old_pause, pause_new=new_pause, threshold=DD_PROTECTION["consecutive_loss_pause"])
    if new_pause != old_pause and new_pause > 0:
        _log.warn("SYSTEM", "dd_pause_armed", consecutive_losses=new_consecutive, pause_signals=new_pause)
    _update_dd_state(new_consecutive, new_pause)


def check_alpha_sweep_breakeven():
    """Check break-even for Micro trades. Filter #27: exclude pending limits."""
    open_trades = execute(
        f"SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL "
        f"AND trade_ref LIKE '{TRADE_REF_PREFIX}%%' AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )

    _log.debug("POSITION", "be_check_tick", open=len(open_trades) if open_trades else 0)
    if not open_trades:
        return

    price = get_current_price(instrument="XAU_USD")
    if not price:
        _log.warn("BROKER", "be_check_no_price")
        return

    # Bug #1 (Jun 18) diagnostic: capture tick freshness so we can detect
    # phantom BE arms caused by stale market_data.json.
    tick_time_str = price.get("time", "")
    tick_age_secs = _compute_tick_age_secs(tick_time_str)

    cfg = MICRO_ALPHA_SWEEP
    for trade in open_trades:
        entry = float(trade["entry_price"])
        tp = float(trade["tp_price"]) if trade["tp_price"] else 0
        sl = float(trade["sl_price"])
        side = trade["side"]

        if tp <= 0:
            _log.debug("POSITION", "be_skip_no_tp", ref=trade["trade_ref"])
            continue

        if side == "LONG":
            if tp <= entry or sl >= entry:
                _log.debug("POSITION", "be_skip_already_armed_or_invalid", ref=trade["trade_ref"], side=side, entry=entry, sl=sl, tp=tp)
                continue
            target_50 = entry + (tp - entry) * cfg["be_trigger_pct"]
            _log.debug("POSITION", "be_progress", ref=trade["trade_ref"], side=side, current_bid=price["bid"], target_50=target_50, entry=entry, tp=tp, distance_to_trigger=target_50-price["bid"])
            if price["bid"] >= target_50:
                new_sl = entry + 0.30
                _log.info("POSITION", "be_triggered", ref=trade["trade_ref"], side=side, trigger_price=price["bid"], target_50=target_50, old_sl=sl, new_sl=new_sl, tick_time=tick_time_str, tick_age_secs=tick_age_secs)
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log.info("POSITION", "be_armed", ref=trade["trade_ref"], side=side, old_sl=sl, new_sl=new_sl, trigger_price=price["bid"])
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["bid"], "source": "scheduler",
                        "tick_time": tick_time_str, "tick_age_secs": tick_age_secs,
                        "trigger_bid": price["bid"], "trigger_ask": price["ask"], "trigger_mid": price.get("mid"), "trigger_spread": price.get("spread"),
                    })
                    print(f"  [MICRO] LONG break-even: SL {sl:.2f} → {new_sl:.2f}")
                else:
                    _log.error("POSITION", "be_modify_failed", ref=trade["trade_ref"], side=side, old_sl=sl, attempted_sl=new_sl, err=result.get("error", "Unknown"))
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                        "tick_time": tick_time_str, "tick_age_secs": tick_age_secs,
                    })
        else:
            if tp >= entry or sl <= entry:
                _log.debug("POSITION", "be_skip_already_armed_or_invalid", ref=trade["trade_ref"], side=side, entry=entry, sl=sl, tp=tp)
                continue
            target_50 = entry - (entry - tp) * cfg["be_trigger_pct"]
            _log.debug("POSITION", "be_progress", ref=trade["trade_ref"], side=side, current_ask=price["ask"], target_50=target_50, entry=entry, tp=tp, distance_to_trigger=price["ask"]-target_50)
            if price["ask"] <= target_50:
                new_sl = entry - 0.30
                _log.info("POSITION", "be_triggered", ref=trade["trade_ref"], side=side, trigger_price=price["ask"], target_50=target_50, old_sl=sl, new_sl=new_sl, tick_time=tick_time_str, tick_age_secs=tick_age_secs)
                result = modify_stop_loss(trade["oanda_trade_id"], new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log.info("POSITION", "be_armed", ref=trade["trade_ref"], side=side, old_sl=sl, new_sl=new_sl, trigger_price=price["ask"])
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["ask"], "source": "scheduler",
                        "tick_time": tick_time_str, "tick_age_secs": tick_age_secs,
                        "trigger_bid": price["bid"], "trigger_ask": price["ask"], "trigger_mid": price.get("mid"), "trigger_spread": price.get("spread"),
                    })
                    print(f"  [MICRO] SHORT break-even: SL {sl:.2f} → {new_sl:.2f}")
                else:
                    _log.error("POSITION", "be_modify_failed", ref=trade["trade_ref"], side=side, old_sl=sl, attempted_sl=new_sl, err=result.get("error", "Unknown"))
                    _log_journal(trade["trade_ref"], trade["strategy"], "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                        "tick_time": tick_time_str, "tick_age_secs": tick_age_secs,
                    })


def check_alpha_sweep_partial_tp():
    """Filter #7 — Gold Micro variant. Strategy='micro_alpha_sweep', instrument='XAU_USD',
    config from MICRO_ALPHA_SWEEP. Mirror of Oil Macro's check_alpha_sweep_partial_tp.
    """
    partial_at = MICRO_ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    partial_sz = MICRO_ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_at <= 0 or partial_sz <= 0:
        return

    # Filter #27: exclude pending limits.
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND strategy='micro_alpha_sweep' "
        "AND oanda_trade_id IS NOT NULL AND COALESCE(partial_done, FALSE) = FALSE "
        "AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )
    _log.debug("POSITION", "partial_check_tick", open=len(open_trades) if open_trades else 0,
               partial_at=partial_at, partial_sz=partial_sz)
    if not open_trades:
        return

    price = get_current_price(instrument="XAU_USD")
    if not price:
        _log.warn("BROKER", "partial_check_no_price")
        return

    from backend.execution import close_partial_trade

    for trade in open_trades:
        try:
            entry = float(trade["entry_price"])
            tp = float(trade["tp_price"]) if trade["tp_price"] else 0
            side = trade["side"]
            oid = trade["oanda_trade_id"]
            units = int(trade["units"])
            if tp <= 0 or units < 2:
                continue

            partial_target = entry + (tp - entry) * partial_at

            if side == "LONG":
                if tp <= entry:
                    continue
                reached = price["bid"] >= partial_target
            else:
                if tp >= entry:
                    continue
                reached = price["ask"] <= partial_target

            if not reached:
                _log.debug("POSITION", "partial_progress", ref=trade["trade_ref"], side=side,
                           entry=entry, tp=tp, target=partial_target,
                           current=price["bid"] if side == "LONG" else price["ask"])
                continue

            units_to_close = max(1, int(round(units * partial_sz)))
            if units_to_close >= units:
                _log.warn("POSITION", "partial_skip_full_close",
                          ref=trade["trade_ref"], units=units, units_to_close=units_to_close)
                continue

            _log.info("POSITION", "partial_triggered", ref=trade["trade_ref"], side=side,
                      entry=entry, tp=tp, target=partial_target, units=units,
                      units_to_close=units_to_close,
                      current=price["bid"] if side == "LONG" else price["ask"])

            result = close_partial_trade(oid, units_to_close, instrument="XAU_USD")

            if not result.get("success"):
                _log.error("BROKER", "partial_close_failed", ref=trade["trade_ref"],
                           units_to_close=units_to_close, err=result.get("error", "Unknown"))
                _log_journal_safe(trade["trade_ref"], trade["strategy"], "PARTIAL_TP_FAILED", None, {
                    "units_to_close": units_to_close,
                    "error": result.get("error"), "retcode": result.get("retcode"),
                })
                continue

            fill_price = float(result.get("close_price") or partial_target)
            closed_units = int(result.get("closed_units") or units_to_close)
            remaining_units = int(result.get("remaining_units") or (units - units_to_close))
            pnl_per_unit = (fill_price - entry) if side == "LONG" else (entry - fill_price)
            banked_usd = pnl_per_unit * closed_units

            try:
                execute(
                    """UPDATE gd_trades
                       SET partial_done = TRUE,
                           partial_fill_price = %s,
                           partial_units = %s,
                           partial_pnl_usd = %s,
                           units = %s
                       WHERE trade_ref = %s""",
                    (fill_price, closed_units, banked_usd, remaining_units, trade["trade_ref"])
                )
            except Exception as e:
                _log.exception("DB", "partial_db_update_failed",
                               ref=trade["trade_ref"], err=str(e))

            _log_journal_safe(trade["trade_ref"], trade["strategy"], "PARTIAL_TP", fill_price, {
                "side": side, "entry": entry, "tp": tp, "target": partial_target,
                "closed_units": closed_units, "remaining_units": remaining_units,
                "banked_usd": banked_usd, "partial_at_pct": partial_at, "partial_size": partial_sz,
            })

            try:
                notify.partial_tp(trade["trade_ref"], "XAU_USD", closed_units, fill_price,
                                  banked_usd, remaining_units)
            except Exception as e:
                print(f"  [MICRO] notify.partial_tp swallowed exception: {e}")

            print(f"  [MICRO] PARTIAL_TP {trade['trade_ref']} {side}: closed "
                  f"{closed_units}/{units} @ {fill_price:.2f}, banked ${banked_usd:+.2f}, "
                  f"runner={remaining_units}")
        except Exception as e:
            _log.exception("SYSTEM", "partial_check_loop_error",
                           ref=trade.get("trade_ref"), err=str(e))


def reconcile_orphans():
    """Adopt any broker positions that don't have a matching DB row.
    See backend-oil-micro/scanner/live_engine.py for full docstring."""
    try:
        broker_open = get_open_trades(instrument="XAU_USD") or []
    except Exception as e:
        _log.exception("SYSTEM", "reconcile_get_open_trades_failed", err=str(e))
        print(f"  [MICRO] reconcile_orphans: get_open_trades failed: {e}")
        return

    _log.debug("POSITION", "reconcile_tick", broker_open=len(broker_open))
    if not broker_open:
        # Issue #16 fix 2026-06-15: smell detector
        # Filter #27: exclude pending limits — they correctly have no broker position.
        try:
            db_open = execute(
                f"SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL "
                f"AND trade_ref LIKE '{TRADE_REF_PREFIX}%%' "
                f"AND COALESCE(mode, 'live') != 'pending'",
                fetch=True
            )
            db_open_cnt = db_open[0]["cnt"] if db_open else 0
            if db_open_cnt > 0:
                _log.warn("POSITION", "reconcile_empty_but_db_has_open", db_open=db_open_cnt)
        except Exception as e:
            _log.exception("POSITION", "reconcile_empty_check_failed", err=str(e))
        return

    # Look up ANY system's open positions — see backend-oil-micro for full
    # rationale. June 11: cross-system pollution caused Telegram spam.
    # Filter #27: exclude pending limits — oanda_trade_id is a pending ticket
    # for those, must not be matched against broker_open positions.
    db_open_rows = execute(
        "SELECT oanda_trade_id FROM gd_trades "
        "WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL "
        "AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )
    db_open_ids = {str(r["oanda_trade_id"]) for r in (db_open_rows or [])}

    for pos in broker_open:
        broker_id = str(pos.get("id") or pos.get("trade_id") or "")
        if not broker_id or broker_id in db_open_ids:
            continue

        # Skip harness-placed test trades (case-insensitive 'harness' prefix).
        comment = (pos.get("comment") or "")
        if comment.lower().startswith("harness"):
            _log.debug("POSITION", "reconcile_skip_harness", broker_id=broker_id, comment=comment)
            continue

        units_signed = pos.get("currentUnits", 0)
        units = abs(int(round(units_signed)))
        if units < 1:
            # Sub-lot position — likely harness/test trade. Skip; never adopt.
            _log.warn("POSITION", "reconcile_skip_sub_lot", broker_id=broker_id, units_signed=units_signed)
            continue
        side = "LONG" if units_signed > 0 else "SHORT"
        entry_price = float(pos.get("price", 0))
        sl = float(pos.get("sl") or 0)
        tp = float(pos.get("tp") or 0)
        lot_size = units / 100.0  # gold: 1 lot = 100 oz

        trade_ref = f"{TRADE_REF_PREFIX}orphan-{broker_id[-8:]}"
        _log.warn("POSITION", "orphan_detected", broker_id=broker_id, side=side, units=units, entry=entry_price, sl=sl, tp=tp, comment=comment, trade_ref=trade_ref)

        try:
            inserted = execute(
                """INSERT INTO gd_trades (
                       trade_ref, strategy, side, entry_time, entry_price,
                       sl_price, tp_price, lot_size, units, mode, oanda_trade_id
                   )
                   VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)
                   ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING
                   RETURNING id""",
                (trade_ref, "micro_alpha_sweep", side, entry_price,
                 sl, tp, lot_size, units, broker_id),
                fetch=True
            )
        except Exception as e:
            _log.exception("DB", "orphan_adopt_insert_failed", broker_id=broker_id, trade_ref=trade_ref, err=str(e))
            print(f"  [MICRO] reconcile_orphans: INSERT failed for {broker_id}: {e}")
            _log_journal_safe("SYSTEM", "micro_alpha_sweep", "ORPHAN_ADOPT_FAILED",
                              entry_price, {"broker_id": broker_id, "error": str(e)})
            continue

        if not inserted:
            _log.debug("POSITION", "orphan_adopt_conflict_no_insert", broker_id=broker_id, trade_ref=trade_ref)
            continue

        _log.warn("POSITION", "orphan_adopted", trade_ref=trade_ref, broker_id=broker_id, side=side, units=units, entry=entry_price, sl=sl, tp=tp)
        _log_journal_safe(trade_ref, "micro_alpha_sweep", "ORPHAN_ADOPTED",
                          entry_price, {
                              "broker_id": broker_id, "side": side, "units": units,
                              "sl": sl, "tp": tp, "reason": "broker_position_not_in_db",
                          })

        try:
            notify.orphan_adopted(trade_ref, broker_id, "XAU_USD", side, units, entry_price, sl, tp)
        except Exception as e:
            _log.exception("SYSTEM", "orphan_notify_failed", trade_ref=trade_ref, err=str(e))
            print(f"  [MICRO] reconcile_orphans: notify failed: {e}")

        print(f"  [MICRO] ORPHAN ADOPTED: {trade_ref} (broker {broker_id}) — investigate logs")


# ---- Filter #27: pending-order monitor ----
# Mirror of backend-oil/scanner/live_engine.pending_order_monitor.
# See that file for canonical comments + state machine documentation.

import json as _json


# Filter #27 grace fallback (Fix B) — see Oil Macro canonical for full docs.
PENDING_GRACE_SECONDS = 60
_orphan_alerted: set = set()

# M13: persistent-bad-open_price escalation. See Oil Macro canonical.
_bad_open_price_cycles: dict = {}
BAD_OPEN_PRICE_THRESHOLD = 5


def _read_dwx_json(filename: str):
    from backend.execution.mt5_executor import DWX_DIR
    import os.path
    path = os.path.join(DWX_DIR, filename)
    try:
        with open(path, "r") as f:
            return _json.load(f)
    except Exception:
        return None


def _orphan_lookup_ttl_seconds(trade_ref: str) -> Optional[int]:
    """H3 (2026-06-17): journal lookup with config fallback. See backend-oil
    canonical for full rationale. Without the fallback, a None return blocks
    grace-resolution and the orphan row stays forever."""
    # Path 1: journal lookup (canonical).
    try:
        rows = execute(
            "SELECT context FROM gd_journal WHERE trade_ref=%s "
            "AND event_type='LIMIT_PLACED' ORDER BY timestamp DESC LIMIT 1",
            (trade_ref,), fetch=True
        )
        if rows:
            ctx = rows[0]["context"] or {}
            if isinstance(ctx, str):
                ctx = _json.loads(ctx)
            ttl = ctx.get("ttl_seconds")
            if ttl is not None:
                return int(ttl)
            _log.warn("BROKER", "orphan_ttl_lookup_no_field",
                      trade_ref=trade_ref,
                      note="LIMIT_PLACED journal exists but missing ttl_seconds field; falling back to config")
        else:
            _log.warn("BROKER", "orphan_ttl_lookup_no_journal",
                      trade_ref=trade_ref,
                      note="no LIMIT_PLACED journal event; falling back to config")
    except Exception as e:
        _log.exception("DB", "orphan_ttl_lookup_db_error",
                       trade_ref=trade_ref, err=str(e),
                       note="DB error during journal lookup; falling back to config")

    # Path 2: config fallback (Gold Micro uses MICRO_ALPHA_SWEEP).
    try:
        bars = MICRO_ALPHA_SWEEP.get("limit_ttl_bars", 5)
        ttl_fallback = int(bars) * 180
        _log.info("BROKER", "orphan_ttl_lookup_config_fallback",
                  trade_ref=trade_ref, ttl_seconds=ttl_fallback,
                  source="MICRO_ALPHA_SWEEP.limit_ttl_bars")
        return ttl_fallback
    except Exception as e:
        _log.exception("BROKER", "orphan_ttl_lookup_config_failed",
                       trade_ref=trade_ref, err=str(e),
                       note="even config fallback failed — orphan row will NOT resolve via grace")
        return None


def reconcile_broker_pending_orphans():
    """Filter #27 / C3 — see backend-oil canonical for full rationale.
    Cancel broker pendings at our magic with no DB row."""
    pending_file = _read_dwx_json("pending_orders.json") or {}
    if not isinstance(pending_file, dict) or not pending_file:
        return

    db_known = execute(
        "SELECT oanda_trade_id FROM gd_trades WHERE oanda_trade_id IS NOT NULL "
        "AND exit_time IS NULL",
        fetch=True
    ) or []
    db_known_tickets = {str(r["oanda_trade_id"]) for r in db_known}
    OUR_MAGIC = 200000

    for ticket_str, info in pending_file.items():
        if not isinstance(info, dict):
            continue
        ticket = str(ticket_str)
        if ticket in db_known_tickets:
            continue
        magic = info.get("magic")
        try:
            if int(magic) != OUR_MAGIC:
                continue
        except (TypeError, ValueError):
            continue

        symbol = info.get("symbol", "?")
        order_type = info.get("type", "?")
        price = info.get("price", 0)
        comment = info.get("comment", "")
        _log.warn("BROKER", "broker_pending_orphan_detected",
                  ticket=ticket, symbol=symbol, type=order_type,
                  price=price, comment=comment, magic=magic,
                  note="ticket in pending_orders.json but no DB row — race orphan, cancelling")
        try:
            cancel_result = cancel_pending_order(ticket)
        except Exception as e:
            _log.exception("BROKER", "broker_pending_orphan_cancel_failed",
                           ticket=ticket, err=str(e))
            continue

        synthetic_ref = f"GD-MI-orphan-pend-{ticket[-8:]}"
        _log_journal_safe(synthetic_ref, "micro_alpha_sweep",
                          "LIMIT_ORPHAN_PENDING_CANCELLED",
                          float(price) if price else 0, {
                              "instrument": "XAU_USD",
                              "ticket": ticket,
                              "symbol": symbol,
                              "type": order_type,
                              "comment": comment,
                              "cancel_result": cancel_result,
                              "reason": "race_timeout_no_db_row",
                          })
        try:
            notify.send(
                f"⚠️ <b>BROKER PENDING ORPHAN</b>\n"
                f"ticket={ticket} {symbol} {order_type} @ {price}\n"
                f"No DB row — cancelled (race-timeout protection)."
            )
        except Exception as e:
            _log.exception("BROKER", "broker_pending_orphan_notify_failed",
                           ticket=ticket, err=str(e))


def pending_order_monitor():
    """Filter #27 periodic reconciler for mode='pending' rows. See Oil Macro
    canonical implementation for state machine docs.
    Fix B: TTL+grace fallback for broker silent-expire (BUG_FILTER_27_PENDING_RECONCILER_GAP).
    C3: also reconciles broker pendings with no DB row (race-timeout orphans).
    """
    # C3: reconcile broker pendings with no DB row — runs unconditionally
    try:
        reconcile_broker_pending_orphans()
    except Exception as e:
        _log.exception("BROKER", "reconcile_broker_pending_orphans_failed", err=str(e))

    pending_db = execute(
        f"SELECT * FROM gd_trades WHERE exit_time IS NULL "
        f"AND strategy='micro_alpha_sweep' AND COALESCE(mode, 'live') = 'pending' "
        f"AND trade_ref LIKE '{TRADE_REF_PREFIX}%%'",
        fetch=True
    )
    if not pending_db:
        return

    pending_file = _read_dwx_json("pending_orders.json") or {}
    open_file = _read_dwx_json("open_orders.json") or {}
    cancelled_file = _read_dwx_json("cancelled_orders.json") or []
    # M9: keep state + detected_via metadata so the LIMIT_TTL_EXPIRED journal
    # can record which path resolved the cancel:
    #   state         = "EXPIRED" | "CANCELED" | "EXPIRED_POLLED" | "CANCELED_POLLED"
    #   detected_via  = "ontradetrans" | "poll" (Fix A)
    cancelled_tickets: dict = {}
    if isinstance(cancelled_file, list):
        for entry in cancelled_file:
            try:
                t = str(entry.get("ticket", ""))
                if not t:
                    continue
                cancelled_tickets[t] = {
                    "state": entry.get("state", ""),
                    "detected_via": entry.get("detected_via", "ontradetrans"),
                }
            except Exception:
                continue
    pending_tickets = {str(k) for k in pending_file.keys()} if isinstance(pending_file, dict) else set()
    open_tickets = {str(k) for k in open_file.keys()} if isinstance(open_file, dict) else set()

    _log.debug("POSITION", "pending_monitor_tick",
               db_pending=len(pending_db), pending_file=len(pending_tickets),
               open_file=len(open_tickets), cancelled_file=len(cancelled_tickets))

    for row in pending_db:
        ticket = str(row["oanda_trade_id"])
        trade_ref = row["trade_ref"]
        intended_limit = float(row["entry_price"])

        if ticket in pending_tickets:
            continue

        if ticket in open_tickets:
            fill_info = open_file.get(ticket, {})
            # H4 (2026-06-17): validate open_price (see backend-oil canonical
            # for full rationale). Skip this cycle if missing/zero/None — DWX
            # may be mid-write; retry next monitor tick.
            raw_open_price = fill_info.get("open_price")
            if raw_open_price is None or float(raw_open_price) <= 0:
                # M13 — escalate persistent bad data; see Oil Macro canonical.
                prev_count = _bad_open_price_cycles.get(ticket, 0)
                if prev_count == -1:
                    continue
                bad_count = prev_count + 1
                _bad_open_price_cycles[ticket] = bad_count
                _log.warn("BROKER", "limit_filled_missing_open_price",
                          trade_ref=trade_ref, ticket=ticket,
                          raw_open_price=raw_open_price,
                          fill_info_keys=list(fill_info.keys()),
                          bad_cycles=bad_count,
                          threshold=BAD_OPEN_PRICE_THRESHOLD,
                          note="open_price missing/zero/None — DWX may be mid-write; retry next cycle")
                if bad_count >= BAD_OPEN_PRICE_THRESHOLD:
                    _log.error("BROKER", "bad_open_price_persistent",
                               trade_ref=trade_ref, ticket=ticket,
                               bad_cycles=bad_count,
                               raw_open_price=raw_open_price,
                               note=f"persistent bad open_price for {bad_count} cycles "
                                    f"(~{bad_count * 30}s); force-cancelling pending")
                    _log_journal_safe(trade_ref, row["strategy"],
                                      "LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED",
                                      intended_limit, {
                                          "instrument": "XAU_USD", "ticket": ticket,
                                          "bad_cycles": bad_count,
                                          "raw_open_price": raw_open_price,
                                          "fill_info_keys": list(fill_info.keys()),
                                      })
                    try:
                        cancel_pending_order(ticket)
                    except Exception as e:
                        _log.exception("BROKER", "bad_open_price_cancel_failed",
                                       trade_ref=trade_ref, ticket=ticket, err=str(e))
                    try:
                        execute(
                            "UPDATE gd_trades SET exit_time=NOW(), "
                            "exit_reason='LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED' "
                            "WHERE oanda_trade_id=%s AND COALESCE(mode, 'live') = 'pending'",
                            (ticket,)
                        )
                    except Exception as e:
                        _log.exception("DB", "bad_open_price_db_update_failed",
                                       trade_ref=trade_ref, ticket=ticket, err=str(e))
                    try:
                        notify.bad_open_price_persistent(
                            trade_ref, "XAU_USD", ticket,
                            intended_limit, bad_count, raw_open_price,
                        )
                    except Exception as e:
                        _log.exception("BROKER", "bad_open_price_notify_failed",
                                       trade_ref=trade_ref, err=str(e))
                    _bad_open_price_cycles[ticket] = -1
                    _orphan_alerted.discard(ticket)
                continue
            actual_fill = float(raw_open_price)
            # M13: clear bad-data counter on valid fill
            _bad_open_price_cycles.pop(ticket, None)
            broker_open_time = fill_info.get("open_time", "")
            try:
                execute(
                    "UPDATE gd_trades SET mode='live', entry_price=%s WHERE oanda_trade_id=%s "
                    "AND COALESCE(mode, 'live') = 'pending'",
                    (actual_fill, ticket)
                )
            except Exception as e:
                _log.exception("DB", "pending_monitor_fill_update_failed",
                               trade_ref=trade_ref, ticket=ticket, err=str(e))
                continue
            # O4 — fill latency from placement to broker fill.
            from backend.execution.mt5_executor import compute_time_to_fill
            time_to_fill = compute_time_to_fill(row["entry_time"], broker_open_time)
            _log.info("BROKER", "limit_filled", trade_ref=trade_ref, ticket=ticket,
                      intended_limit=intended_limit, actual_fill=actual_fill,
                      broker_open_time=broker_open_time, time_to_fill=time_to_fill)
            _log_journal_safe(trade_ref, row["strategy"], "LIMIT_FILLED", actual_fill, {
                "instrument": "XAU_USD", "ticket": ticket,
                "intended_limit": intended_limit, "actual_fill": actual_fill,
                "broker_open_time": broker_open_time, "time_to_fill": time_to_fill,
            })
            try:
                notify.trade_filled(trade_ref, "XAU_USD", row["side"].lower(),
                                    actual_fill, row["units"],
                                    float(row["sl_price"]),
                                    float(row["tp_price"]) if row["tp_price"] else 0)
            except Exception as e:
                _log.exception("BROKER", "limit_filled_notify_failed",
                               trade_ref=trade_ref, err=str(e))
            _orphan_alerted.discard(ticket)
            print(f"  [MICRO] LIMIT FILLED: {trade_ref} ticket={ticket} @ ${actual_fill:.2f}")
            continue

        if ticket in cancelled_tickets:
            # M9: surface state + detected_via in journal context.
            cancel_meta = cancelled_tickets[ticket]
            try:
                execute(
                    "UPDATE gd_trades SET exit_time=NOW(), exit_reason='LIMIT_TTL_EXPIRED' "
                    "WHERE oanda_trade_id=%s AND COALESCE(mode, 'live') = 'pending'",
                    (ticket,)
                )
            except Exception as e:
                _log.exception("DB", "pending_monitor_expire_update_failed",
                               trade_ref=trade_ref, ticket=ticket, err=str(e))
                continue
            _log.info("BROKER", "limit_ttl_expired", trade_ref=trade_ref,
                      ticket=ticket, intended_limit=intended_limit,
                      state=cancel_meta.get("state"),
                      detected_via=cancel_meta.get("detected_via"))
            _log_journal_safe(trade_ref, row["strategy"], "LIMIT_TTL_EXPIRED",
                              intended_limit, {
                                  "instrument": "XAU_USD", "ticket": ticket,
                                  "intended_limit": intended_limit,
                                  "state": cancel_meta.get("state", ""),
                                  "detected_via": cancel_meta.get("detected_via", "ontradetrans"),
                              })
            try:
                notify.limit_ttl_expired(trade_ref, "XAU_USD", intended_limit)
            except Exception as e:
                _log.exception("BROKER", "limit_ttl_notify_failed",
                               trade_ref=trade_ref, err=str(e))
            _orphan_alerted.discard(ticket)
            print(f"  [MICRO] LIMIT EXPIRED: {trade_ref} ticket={ticket} @ ${intended_limit:.2f}")
            continue

        # Fix B: orphan with grace fallback (see Oil Macro canonical for docs)
        ttl_seconds = _orphan_lookup_ttl_seconds(trade_ref)
        entry_time = row["entry_time"]
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed = (now - entry_time).total_seconds()
        past_grace = (ttl_seconds is not None) and (elapsed > ttl_seconds + PENDING_GRACE_SECONDS)

        if past_grace:
            try:
                execute(
                    "UPDATE gd_trades SET exit_time=NOW(), "
                    "exit_reason='LIMIT_TTL_EXPIRED_GRACE' "
                    "WHERE oanda_trade_id=%s AND COALESCE(mode, 'live') = 'pending'",
                    (ticket,)
                )
            except Exception as e:
                _log.exception("DB", "pending_monitor_grace_update_failed",
                               trade_ref=trade_ref, ticket=ticket, err=str(e))
                continue
            _log.warn("BROKER", "limit_ttl_expired_grace",
                      trade_ref=trade_ref, ticket=ticket,
                      intended_limit=intended_limit,
                      elapsed_seconds=int(elapsed), ttl_seconds=ttl_seconds,
                      note="broker silent-expire fallback (Fix B)")
            _log_journal_safe(trade_ref, row["strategy"], "LIMIT_TTL_EXPIRED",
                              intended_limit, {
                                  "instrument": "XAU_USD", "ticket": ticket,
                                  "intended_limit": intended_limit,
                                  "exit_reason": "LIMIT_TTL_EXPIRED_GRACE",
                                  "elapsed_seconds": int(elapsed),
                                  "ttl_seconds": ttl_seconds,
                                  "fallback": "fix_b_grace",
                              })
            try:
                # M10: distinct Telegram suffix for grace fallback path.
                notify.limit_ttl_expired(trade_ref, "XAU_USD", intended_limit,
                                         via_grace=True)
            except Exception as e:
                _log.exception("BROKER", "limit_ttl_grace_notify_failed",
                               trade_ref=trade_ref, err=str(e))
            _orphan_alerted.discard(ticket)
            print(f"  [MICRO] LIMIT EXPIRED (grace fallback): {trade_ref} ticket={ticket} @ ${intended_limit:.2f}")
            continue

        # Within grace: warn + throttled Telegram (Fix C)
        _log.warn("POSITION", "pending_monitor_orphan",
                  trade_ref=trade_ref, ticket=ticket,
                  elapsed_seconds=int(elapsed), ttl_seconds=ttl_seconds,
                  note="ticket not in pending/open/cancelled files; "
                       "within grace, will resolve at TTL+60s")
        if ticket not in _orphan_alerted:
            _orphan_alerted.add(ticket)
            # M8: persist orphan event to gd_journal so postmortem can reconstruct
            # broker-visibility gap from DB even after file logs rotate. Throttled
            # via _orphan_alerted (1× per ticket) — same gate as Telegram.
            _log_journal_safe(trade_ref, row["strategy"], "LIMIT_ORPHAN",
                              intended_limit, {
                                  "instrument": "XAU_USD", "ticket": ticket,
                                  "intended_limit": intended_limit,
                                  "elapsed_seconds": int(elapsed),
                                  "ttl_seconds": ttl_seconds,
                                  "note": "ticket missing from pending/open/cancelled; within grace",
                              })
            try:
                notify.limit_orphan_warn(trade_ref, "XAU_USD", ticket,
                                         intended_limit, int(elapsed))
            except Exception as e:
                _log.exception("BROKER", "orphan_alert_notify_failed",
                               trade_ref=trade_ref, err=str(e))
