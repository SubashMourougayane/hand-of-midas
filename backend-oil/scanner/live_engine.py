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
    get_current_price, place_market_order, place_limit_order,
    cancel_pending_order,
    close_trade, get_open_trades, get_account_summary,
    modify_stop_loss, get_trade_details,
)
from backend.execution.limit_price import compute_limit_price, parse_dry_run_env

def _get_gbp_usd_rate():
    """Oil account is USD — no conversion needed."""
    return 1.0
from backend.db import execute, safe_json_dumps
from backend import notify
from config import STRATEGY_RISK, MAX_UNITS, ALPHA_SWEEP, slippage
from scanner import _log

# Per-trade EXIT_AMBIGUOUS streak counter. Cleared on success or close-resolution.
# A few cycles is normal (DWX file race during close). Sustained = DWX EA broken;
# fire a Telegram alert at threshold so a stuck Macro trade can't go unnoticed.
_exit_ambiguous_streak: dict = {}
_EXIT_AMBIGUOUS_ALERT_CYCLES = 5

# Per-trade MAX_HOLD market-closed defer state — see backend/scanner/live_engine.py
# for the canonical comment. Notify ONCE on first defer, subsequent failures
# stay silent, eventual successful close labels reason "MAX_HOLD (deferred)".
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

# Filter #6: post-BE high-water-mark per trade. Keyed by oanda_trade_id.
# For LONG: tracks highest bid seen since BE armed.
# For SHORT: tracks lowest ask seen since BE armed.
# Used to compute trail SL = entry ± (hwm - entry) × ALPHA_SWEEP["trail_after_be_pct"].
# SL only ratchets in favorable direction (high-water-mark semantics).
_post_be_hwm: dict = {}


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
    """Best-effort journal write — NEVER raises.
    Issue #15 fix 2026-06-15: also emit structured _log.exception so failures
    are visible in debug API + log files, not just stdout.
    """
    try:
        _log_journal(trade_ref, strategy, event_type, price, context)
    except Exception as e:
        try:
            _log.exception("JOURNAL", "log_journal_failed",
                           trade_ref=trade_ref, event_type=event_type, err=str(e))
        except Exception:
            pass
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
    # SCOPE: Oil-Macro only — exclude Oil Micro (OIL-MI-) trades.
    # Issue #2 fix 2026-06-15: 'OIL-%' matched OIL-AS- AND OIL-MI-, polluted equity-MA.
    rows = execute(
        "SELECT pnl_usd FROM gd_trades WHERE exit_time IS NOT NULL AND strategy = 'alpha_sweep_oil' ORDER BY exit_time DESC LIMIT 20",
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
    # Issue #6 fix 2026-06-15: sanity floor — refuse to size if equity < $100.
    if equity_usd is None or equity_usd < 100:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="equity_too_low")
        print(f"  [OIL] SKIP: equity ${equity_usd} below $100 floor")
        return None

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

    # Defense-in-depth: open-position guard at execute_signal layer.
    # Same pattern as Gold Macro fix 2026-06-15.
    open_oil_macro = execute(
        "SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL AND trade_ref LIKE 'OIL-AS-%%'",
        fetch=True
    )
    if open_oil_macro and open_oil_macro[0]["cnt"] > 0:
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="position_already_open")
        print(f"  [OIL] SKIP: already have open Oil-Macro position")
        return None

    # M12 (2026-06-17): validate SL distance from current price (broker minimum
    # stop level). Mirror of backend-oil-micro/scanner/live_engine.py:182-194.
    # Without this check, signals with SL too close to market reach the broker
    # and get rejected with retcode 10016. Production evidence: 4 OIL-AS
    # historical 10016 rejects (Jun 2 + Jun 9). Pre-emptive skip = cleaner
    # gd_signals classification + cleaner postmortem trail.
    # See docs/FILTER_27_AUDIT_BACKLOG.md M12.
    price_now = get_current_price(instrument="BCO_USD")
    if price_now:
        current_ask = price_now["ask"]
        current_bid = price_now["bid"]
        if direction == "short" and sl_price <= current_ask + 0.05:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_too_close_to_price")
            print(f"  [OIL] SKIP: SL ${sl_price:.4f} too close to ask ${current_ask:.4f}")
            return None
        if direction == "long" and sl_price >= current_bid - 0.05:
            _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason="sl_too_close_to_price")
            print(f"  [OIL] SKIP: SL ${sl_price:.4f} too close to bid ${current_bid:.4f}")
            return None

    oanda_units = units if direction == "long" else -units

    # Filter #27: compute the limit_price the BT engine would use for this signal,
    # using the SAME helper. Whether we ACT on it depends on entry_mode + LIMIT_DRY_RUN.
    cfg_entry_mode = ALPHA_SWEEP.get("entry_mode", "market")
    # M2 (2026-06-17): log resolved entry_mode so config typos like "Limit"
    # or "LIMIT" are visible. Strict-equality check below treats anything
    # other than literal "limit" as market. See docs/FILTER_27_AUDIT_BACKLOG.md M2.
    will_use_limit = (cfg_entry_mode == "limit")
    _log.info("BROKER", "entry_mode_resolved",
              raw=cfg_entry_mode, will_use_limit=will_use_limit, trade_ref=trade_ref)
    if cfg_entry_mode == "limit":
        # Live needs the engulfing-bar bid/ask close. We only have the strategy's
        # entry_price + risk in this scope. For variant B (engulf_close) we
        # call get_current_price() as a proxy. NOTE: tiny live↔BT drift on
        # variant B (live samples the latest tick; BT samples the engulfing-bar's
        # exact close). Tightened by passing bar OHLC via context in a later commit.
        limit_offset_pct = ALPHA_SWEEP.get("limit_offset_pct", 0.0)
        limit_ttl_bars = ALPHA_SWEEP.get("limit_ttl_bars", 5)
        ttl_seconds = limit_ttl_bars * 180  # M3 = 180s/bar
        risk_distance = abs(entry_price - sl_price)
        live_price = get_current_price("BCO_USD")
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
            # M3 (2026-06-17): journal the limit→market fall-back so operators
            # who opted into limit mode can spot when it didn't fire. Currently
            # silent (only _log.exception), which is fine for crash forensics
            # but invisible in the journal trail. See docs/FILTER_27_AUDIT_BACKLOG.md M3.
            _log_journal_safe(trade_ref, strategy, "LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET",
                              entry_price, {
                                  "instrument": "BCO_USD",
                                  "error": str(e),
                                  "entry_price": entry_price,
                                  "sl_price": sl_price,
                                  "tp_price": tp_price,
                                  "offset_pct": str(limit_offset_pct),
                                  "fallback_action": "market_order",
                              })

        # Dry-run gate. Default ON (LIMIT_DRY_RUN unset = "true") so we don't
        # accidentally place a live limit before the operator explicitly opts in.
        # H1 + M7 (2026-06-17): parse_dry_run_env handles whitespace + per-system
        # override. Per-system: OIL_LIMIT_DRY_RUN wins, falls back to global
        # LIMIT_DRY_RUN. Enables single-system rollback without flipping all 3.
        # See docs/FILTER_27_AUDIT_BACKLOG.md H1+M7.
        dry_run = parse_dry_run_env(system_prefix="OIL")

        if intended_limit is not None:
            # H6 (2026-06-17): refuse to place a limit price clearly through
            # current market. Production rate to date: 0/4 trip rate, but
            # market-moving-while-engulfing-bar-forms could land limit ABOVE
            # current ask (LONG) or BELOW current bid (SHORT) — broker would
            # either instant-fill at unintended price OR reject 10015. We use
            # PERMISSIVE thresholds (only kill if CLEARLY through ask/bid)
            # so we don't kill working between-bid-ask placements like
            # OIL-MI-08b725d3 (verified safe with permissive threshold).
            # See docs/FILTER_27_AUDIT_BACKLOG.md H6.
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
                                          "instrument": "BCO_USD",
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
                                          "instrument": "BCO_USD",
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
                                      "instrument": "BCO_USD",
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
                                      "instrument": "BCO_USD",
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
                "instrument": "BCO_USD",
                "intended_limit": intended_limit,
                "entry_price": entry_price,
                "ttl_seconds": ttl_seconds,
                "offset_pct": str(limit_offset_pct),
                "dry_run": dry_run,
                "actual_path": "market_order" if dry_run else "limit_order_pending",
            })

            if not dry_run:
                # REAL LIMIT PATH — places the pending order and returns trade_ref.
                # The pending_order_monitor_job (scheduler.py, every 30s) handles
                # fill detection and TTL-cancel reconciliation. Broker's own
                # ORDER_TIME_SPECIFIED expiration auto-cancels at TTL.
                _log.info("BROKER", "limit_order_placing", direction=direction,
                          units=units, limit_price=intended_limit, sl=sl_price,
                          tp=tp_price, ttl_seconds=ttl_seconds, trade_ref=trade_ref)
                print(f"  [OIL] Placing {direction.upper()} {units} barrels @ LIMIT "
                      f"${intended_limit:.4f}, SL={sl_price:.4f}, TP={tp_price:.4f}, "
                      f"TTL={ttl_seconds}s")
                limit_result = place_limit_order(
                    instrument="BCO_USD",
                    units=oanda_units,
                    limit_price=intended_limit,
                    sl=sl_price,
                    tp=tp_price,
                    ttl_seconds=ttl_seconds,
                    comment=f"alpha_sweep_oil|{trade_ref}",
                )
                if not limit_result.get("success"):
                    error = limit_result.get("error", "Unknown")
                    _log.error("BROKER", "limit_order_failed", direction=direction,
                               units=units, err=error, trade_ref=trade_ref)
                    _log_signal(strategy, direction, entry_price, sl_price, tp_price,
                                taken=False, skip_reason=f"limit_order_error: {error}")
                    _log_journal(trade_ref, strategy, "LIMIT_ORDER_FAILED", entry_price,
                                 {"error": error, "instrument": "BCO_USD",
                                  "intended_limit": intended_limit})
                    print(f"  [OIL] Limit order FAILED: {error}")
                    return None

                # Limit accepted by broker. Persist as pending row.
                # mode='pending' => excluded from reconciler queries (commit b998a43);
                # one-at-a-time guard still counts it (intentional).
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
                         tp_price, units / 1000.0, units, pending_ticket)
                    )
                except Exception as e:
                    # Limit is on broker. DB insert failed → orphan-protection kicks
                    # in via daily recon. Do NOT cancel — we'd lose the limit and
                    # potentially miss a fill while the recon catches up.
                    _log.exception("DB", "pending_insert_failed_orphan_risk",
                                   trade_ref=trade_ref, oanda_id=pending_ticket,
                                   limit_price=intended_limit, err=str(e))
                    print(f"  [OIL] DB INSERT FAILED (limit is pending on broker!): {e}")
                    try:
                        _log_journal(trade_ref, strategy, "DB_INSERT_FAILED",
                                     intended_limit, {"error": str(e),
                                                       "oanda_id": pending_ticket,
                                                       "kind": "pending"})
                    except Exception:
                        pass

                _log_journal_safe(trade_ref, strategy, "LIMIT_PLACED", intended_limit, {
                    "instrument": "BCO_USD", "units": units, "sl": sl_price, "tp": tp_price,
                    "ticket": pending_ticket, "ttl_seconds": ttl_seconds,
                    "expiration": limit_result.get("expiration_time"),
                    "risk_mult": risk_mult, "risk_pct": risk_pct, "equity_usd": equity_usd,
                })
                try:
                    notify.limit_placed(trade_ref, "BCO_USD", direction,
                                        intended_limit, ttl_seconds)
                except Exception as e:
                    print(f"  [OIL] notify.limit_placed swallowed exception: {e}")
                # M11: limit-success path was missing _log_signal(taken=True),
                # so gd_signals had NO row for this trade. Cooldown query in
                # scheduler.py:127 ORDER BY timestamp DESC LIMIT 1 then found
                # the LAST signal (could be hours earlier) → 5-min cooldown
                # gate fails open → next scan tick could re-fire same setup.
                # Wrap in try/except: broker order is live; must not crash here.
                try:
                    _log_signal(strategy, direction, intended_limit, sl_price,
                                tp_price, taken=True, trade_ref=trade_ref)
                except Exception as e:
                    print(f"  [OIL] _log_signal FAILED (limit path): {e}")
                print(f"  [OIL] LIMIT PLACED: ticket={pending_ticket} @ ${intended_limit:.4f}")
                return trade_ref  # ALWAYS return trade_ref — pending exists on broker

    _log.info("BROKER", "order_placing", direction=direction, units=units, sl=sl_price, tp=tp_price, trade_ref=trade_ref)
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
        _log.error("BROKER", "order_failed", direction=direction, units=units, err=error, trade_ref=trade_ref)
        _log_signal(strategy, direction, entry_price, sl_price, tp_price, taken=False, skip_reason=f"oanda_error: {error}")
        _log_journal(trade_ref, strategy, "ORDER_FAILED", entry_price, {"error": error, "instrument": "BCO_USD"})
        print(f"  [OIL] Order FAILED: {error}")
        return None

    fill_price = result["fill_price"]
    oanda_trade_id = result["trade_id"]
    _log.info("BROKER", "order_filled", direction=direction, units=units, fill=fill_price, oanda_id=oanda_trade_id, trade_ref=trade_ref)

    # Wrap _log_signal — if it raises (numpy serialization etc.), order is
    # already on broker and we must not crash before journaling/notify.
    try:
        _log_signal(strategy, direction, fill_price, sl_price, tp_price, taken=True, trade_ref=trade_ref)
    except Exception as e:
        print(f"  [OIL] _log_signal FAILED: {e}")

    # Wrap the gd_trades INSERT. If it fails (rare — UniqueViolation against
    # the partial unique index if reconciler raced ahead, or DB outage), the
    # broker order is already live. Journal a DB_INSERT_FAILED event so the
    # daily recon flags it; the orphan reconciler will adopt the position
    # within 60s using the broker_id it can read from open_orders.json.
    try:
        execute(
            """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
               VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, 'live', %s)""",
            (trade_ref, strategy, direction.upper(), fill_price, sl_price, tp_price, units / 1000.0, units, oanda_trade_id)
        )
    except Exception as e:
        _log.exception("DB", "trade_insert_failed_orphan_risk", trade_ref=trade_ref, oanda_id=oanda_trade_id, fill=fill_price, err=str(e))
        print(f"  [OIL] DB INSERT FAILED (trade is open on broker!): {e}")
        try:
            _log_journal(trade_ref, strategy, "DB_INSERT_FAILED", fill_price, {"error": str(e), "oanda_id": oanda_trade_id})
        except Exception:
            pass

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
    # Filter #27: pending-limit rows have mode='pending' and oanda_trade_id set
    # to the pending TICKET (not a position id). They MUST be excluded from
    # the position-reconciler — otherwise we'd treat the pending ticket as a
    # missing OANDA position and try to detect SL/TP exit reasons against a
    # price that hasn't filled yet. Pending rows are handled by
    # pending_order_monitor_job (separate path).
    open_db_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND oanda_trade_id IS NOT NULL "
        "AND trade_ref LIKE 'OIL-%%' AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )

    _log.debug("POSITION", "tick", open=len(open_db_trades) if open_db_trades else 0)
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
                        _update_dd_after_exit(realized_pl, pnl_usd)
                        _post_be_hwm.pop(trade.get("oanda_trade_id"), None)  # Filter #6: clean up trail HWM
                        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "EXIT_FILLED", result["close_price"], {
                            "reason": exit_reason, "bars_held": int(bars_held),
                            "pnl_gbp": realized_pl, "pnl_usd": pnl_usd,
                        })
                        notify.trade_closed(trade["trade_ref"], "BCO_USD", exit_reason, realized_pl, pnl_usd)
                    elif _is_market_closed_error(result):
                        already_notified = _max_hold_deferred.get(oanda_id, False)
                        _max_hold_deferred[oanda_id] = True
                        _log.warn("EXIT", "max_hold_deferred", trade_ref=trade["trade_ref"], oanda_id=oanda_id,
                            bars_held=int(bars_held), error=result.get("error"), retcode=result.get("retcode"),
                            first_notify=not already_notified)
                        if not already_notified:
                            _log_journal(trade["trade_ref"], "alpha_sweep_oil", "MAX_HOLD_DEFERRED", None, {
                                "reason": "market_closed", "bars_held": int(bars_held),
                                "error": result.get("error"), "retcode": result.get("retcode"),
                            })
                            notify.max_hold_deferred(trade["trade_ref"], "BCO_USD")
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
            # Either way, do NOT guess. Skip and retry next cycle. Use
            # _log_journal_safe: we're in a failure-recovery code path.
            streak = _exit_ambiguous_streak.get(oanda_id, 0) + 1
            _exit_ambiguous_streak[oanda_id] = streak
            _log.warn("EXIT", "ambiguous", trade_ref=trade["trade_ref"], oanda_id=oanda_id, reason="no_open_no_closed_record", streak=streak)
            print(f"  [OIL] Position {oanda_id} not in open_orders, no closed_orders entry yet — "
                  f"skipping; will retry next cycle (race or pending close, streak={streak})")
            _log_journal_safe(trade["trade_ref"], "alpha_sweep_oil", "EXIT_AMBIGUOUS", None, {
                "oanda_id": oanda_id,
                "reason": "no_open_no_closed_record",
                "streak": streak,
            })
            if streak == _EXIT_AMBIGUOUS_ALERT_CYCLES:
                try:
                    notify.error(
                        f"[OIL] {trade['trade_ref']} stuck in EXIT_AMBIGUOUS for "
                        f"{streak} cycles. DWX EA may not be writing closed_orders.json. "
                        f"Investigate."
                    )
                except Exception as e:
                    # Issue #14 fix 2026-06-15
                    _log.exception("NOTIFY", "exit_ambiguous_alert_failed",
                                   trade_ref=trade["trade_ref"], err=str(e))
                    _exit_ambiguous_streak[oanda_id] = streak - 1
            continue

        if details.get("state") != "CLOSED":
            # Position is actually still open per get_trade_details — DWX
            # open_orders.json was stale when we read it. Skip and retry.
            _exit_ambiguous_streak.pop(oanda_id, None)
            continue

        # AUTHORITATIVE: real broker fill data — clear ambiguous streak.
        _exit_ambiguous_streak.pop(oanda_id, None)
        _post_be_hwm.pop(oanda_id, None)  # Filter #6: clean up trail HWM
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

        _log.info("EXIT", "detected", trade_ref=trade["trade_ref"], reason=exit_reason, fill=fill_price, pnl_usd=pnl_usd, oanda_id=oanda_id)
        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "EXIT_FILLED", fill_price, {
            "reason": exit_reason, "pnl_gbp": realized_pl, "pnl_usd": pnl_usd,
            "oanda_id": oanda_id, "instrument": "BCO_USD",
        })
        print(f"  [OIL] Trade {trade['trade_ref']} closed: {exit_reason} @ ${fill_price:.2f}, P&L=${pnl_usd:.2f}")
        notify.trade_closed(trade["trade_ref"], "BCO_USD", exit_reason, realized_pl, pnl_usd)


def _update_dd_after_exit(realized_pl_gbp: float, pnl_usd: float):
    """Update DD state after a trade closes."""
    dd_state = _get_dd_state()
    old_consecutive = dd_state["consecutive_losses"]
    old_pause = dd_state["pause_counter"]
    old_equity = float(dd_state["equity"])
    if realized_pl_gbp > 0:
        new_consecutive = 0
    else:
        new_consecutive = dd_state["consecutive_losses"] + 1
        if new_consecutive >= 5:
            execute("UPDATE gd_dd_state SET pause_counter = 2 WHERE id = 2")
            _log.warn("SYSTEM", "dd_pause_armed", consecutive_losses=new_consecutive, pause_signals=2)
    new_equity = float(dd_state["equity"]) + pnl_usd
    new_peak = max(float(dd_state["peak_equity"]), new_equity)
    _log.info("SYSTEM", "dd_state_update", pl=realized_pl_gbp, pnl_usd=pnl_usd, consec_old=old_consecutive, consec_new=new_consecutive, equity_old=old_equity, equity_new=new_equity, peak=new_peak)
    _update_dd_state(new_consecutive, dd_state["pause_counter"], new_equity, new_peak)


def check_alpha_sweep_breakeven():
    """Scheduler fallback: check break-even for Oil trades (stream is primary).

    Filter #27: COALESCE excludes mode='pending' rows. BE check on a
    not-yet-filled limit would corrupt the BE state machine.
    """
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND strategy='alpha_sweep_oil' "
        "AND oanda_trade_id IS NOT NULL AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )

    _log.debug("POSITION", "be_check_tick", open=len(open_trades) if open_trades else 0)
    if not open_trades:
        return

    price = get_current_price(instrument="BCO_USD")
    if not price:
        _log.warn("BROKER", "be_check_no_price")
        return

    for trade in open_trades:
        entry = float(trade["entry_price"])
        tp = float(trade["tp_price"]) if trade["tp_price"] else 0
        sl = float(trade["sl_price"])
        side = trade["side"]

        if tp <= 0:
            _log.debug("POSITION", "be_skip_no_tp", ref=trade["trade_ref"])
            continue

        oid = trade["oanda_trade_id"]
        trail_pct = ALPHA_SWEEP.get("trail_after_be_pct", 0.0)

        if side == "LONG":
            if tp <= entry:
                continue
            # Already armed → check if we should trail (Filter #6).
            if sl >= entry:
                if trail_pct <= 0:
                    _log.debug("POSITION", "be_skip_already_armed", ref=trade["trade_ref"], side=side, sl=sl, entry=entry)
                    continue
                # Update HWM (longs: highest bid seen post-BE)
                cur = price["bid"]
                hwm = _post_be_hwm.get(oid, cur)
                if cur > hwm:
                    hwm = cur
                _post_be_hwm[oid] = hwm
                proposed_sl = entry + (hwm - entry) * trail_pct
                # Cap at TP - small buffer to avoid SL >= TP race
                proposed_sl = min(proposed_sl, tp - 0.05)
                if proposed_sl > sl + 0.005:  # 0.5c minimum delta to avoid noisy modifies
                    _log.info("POSITION", "trail_triggered", ref=trade["trade_ref"], side=side,
                              hwm=hwm, current_bid=cur, old_sl=sl, new_sl=proposed_sl, trail_pct=trail_pct)
                    result = modify_stop_loss(oid, proposed_sl)
                    if result.get("success"):
                        execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (proposed_sl, trade["trade_ref"]))
                        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "TRAIL_SL", proposed_sl, {
                            "old_sl": sl, "hwm": hwm, "trail_pct": trail_pct, "source": "scheduler",
                        })
                        print(f"  [OIL] LONG trail: SL {sl:.4f} → {proposed_sl:.4f}  (hwm={hwm:.4f})")
                    else:
                        _log.error("POSITION", "trail_modify_failed", ref=trade["trade_ref"], side=side,
                                   old_sl=sl, attempted_sl=proposed_sl, err=result.get("error", "Unknown"))
                continue
            # Not yet armed: regular BE check
            target_50 = entry + (tp - entry) * ALPHA_SWEEP["be_trigger_pct"]
            _log.debug("POSITION", "be_progress", ref=trade["trade_ref"], side=side, current_bid=price["bid"], target_50=target_50, entry=entry, tp=tp, distance_to_trigger=target_50-price["bid"])
            if price["bid"] >= target_50:
                new_sl = entry + 0.01
                _log.info("POSITION", "be_triggered", ref=trade["trade_ref"], side=side, trigger_price=price["bid"], target_50=target_50, old_sl=sl, new_sl=new_sl)
                result = modify_stop_loss(oid, new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log.info("POSITION", "be_armed", ref=trade["trade_ref"], side=side, old_sl=sl, new_sl=new_sl, trigger_price=price["bid"])
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["bid"], "source": "scheduler",
                    })
                    notify.break_even(trade["trade_ref"], "BCO_USD", new_sl)
                    # Initialize HWM for the trail (if enabled)
                    if trail_pct > 0:
                        _post_be_hwm[oid] = price["bid"]
                    print(f"  [OIL] LONG break-even: SL {sl:.4f} → {new_sl:.4f}")
                else:
                    _log.error("POSITION", "be_modify_failed", ref=trade["trade_ref"], side=side, old_sl=sl, attempted_sl=new_sl, err=result.get("error", "Unknown"))
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                    })
        else:
            if tp >= entry:
                continue
            # Already armed → check trail
            if sl <= entry:
                if trail_pct <= 0:
                    _log.debug("POSITION", "be_skip_already_armed", ref=trade["trade_ref"], side=side, sl=sl, entry=entry)
                    continue
                # SHORT: HWM = lowest ask seen post-BE
                cur = price["ask"]
                hwm = _post_be_hwm.get(oid, cur)
                if cur < hwm:
                    hwm = cur
                _post_be_hwm[oid] = hwm
                proposed_sl = entry - (entry - hwm) * trail_pct
                proposed_sl = max(proposed_sl, tp + 0.05)
                if proposed_sl < sl - 0.005:
                    _log.info("POSITION", "trail_triggered", ref=trade["trade_ref"], side=side,
                              hwm=hwm, current_ask=cur, old_sl=sl, new_sl=proposed_sl, trail_pct=trail_pct)
                    result = modify_stop_loss(oid, proposed_sl)
                    if result.get("success"):
                        execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (proposed_sl, trade["trade_ref"]))
                        _log_journal(trade["trade_ref"], "alpha_sweep_oil", "TRAIL_SL", proposed_sl, {
                            "old_sl": sl, "hwm": hwm, "trail_pct": trail_pct, "source": "scheduler",
                        })
                        print(f"  [OIL] SHORT trail: SL {sl:.4f} → {proposed_sl:.4f}  (hwm={hwm:.4f})")
                    else:
                        _log.error("POSITION", "trail_modify_failed", ref=trade["trade_ref"], side=side,
                                   old_sl=sl, attempted_sl=proposed_sl, err=result.get("error", "Unknown"))
                continue
            # Not yet armed: regular BE check
            target_50 = entry - (entry - tp) * ALPHA_SWEEP["be_trigger_pct"]
            _log.debug("POSITION", "be_progress", ref=trade["trade_ref"], side=side, current_ask=price["ask"], target_50=target_50, entry=entry, tp=tp, distance_to_trigger=price["ask"]-target_50)
            if price["ask"] <= target_50:
                new_sl = entry - 0.01
                _log.info("POSITION", "be_triggered", ref=trade["trade_ref"], side=side, trigger_price=price["ask"], target_50=target_50, old_sl=sl, new_sl=new_sl)
                result = modify_stop_loss(oid, new_sl)
                if result.get("success"):
                    execute("UPDATE gd_trades SET sl_price = %s WHERE trade_ref = %s", (new_sl, trade["trade_ref"]))
                    _log.info("POSITION", "be_armed", ref=trade["trade_ref"], side=side, old_sl=sl, new_sl=new_sl, trigger_price=price["ask"])
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN", new_sl, {
                        "old_sl": sl, "trigger_price": price["ask"], "source": "scheduler",
                    })
                    notify.break_even(trade["trade_ref"], "BCO_USD", new_sl)
                    if trail_pct > 0:
                        _post_be_hwm[oid] = price["ask"]
                    print(f"  [OIL] SHORT break-even: SL {sl:.4f} → {new_sl:.4f}")
                else:
                    _log.error("POSITION", "be_modify_failed", ref=trade["trade_ref"], side=side, old_sl=sl, attempted_sl=new_sl, err=result.get("error", "Unknown"))
                    _log_journal(trade["trade_ref"], "alpha_sweep_oil", "BREAK_EVEN_FAILED", None, {
                        "old_sl": sl, "attempted_sl": new_sl, "error": result.get("error", "Unknown"),
                    })


def check_alpha_sweep_partial_tp():
    """Filter #7: bank `partial_tp_size` of the position when bar reaches halfway.

    Runs every scheduler tick alongside check_alpha_sweep_breakeven. For each
    open Alpha-Sweep trade not yet partial'd:
      1. Read partial_tp_at_pct + partial_tp_size from ALPHA_SWEEP config.
      2. Skip if either is 0 (filter disabled for this system).
      3. Skip if partial_done=true (already fired — idempotency).
      4. Compute partial_target = entry + (tp - entry) × partial_tp_at_pct.
      5. If price has reached the target, send CLOSE_PARTIAL for units_to_close.
      6. On success: mark partial_done=true, persist fill price + banked P&L,
         journal, Telegram.

    Same execution rules as Variant A (BE on schedule unchanged) — partial_arms_be
    is wired but defaults False per shipped config.
    """
    partial_at = ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    partial_sz = ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_at <= 0 or partial_sz <= 0:
        return  # filter off

    # Filter #27: exclude mode='pending' rows — partial-TP requires a filled
    # position, not a not-yet-triggered limit.
    open_trades = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL AND strategy='alpha_sweep_oil' "
        "AND oanda_trade_id IS NOT NULL AND COALESCE(partial_done, FALSE) = FALSE "
        "AND COALESCE(mode, 'live') != 'pending'",
        fetch=True
    )
    _log.debug("POSITION", "partial_check_tick", open=len(open_trades) if open_trades else 0,
               partial_at=partial_at, partial_sz=partial_sz)
    if not open_trades:
        return

    price = get_current_price(instrument="BCO_USD")
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
                # No TP set or position too small to halve — skip.
                continue

            partial_target = entry + (tp - entry) * partial_at  # signed; works for both sides

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
                # Edge case: rounding pushed it to full close. Skip — let TP/SL/BE handle.
                _log.warn("POSITION", "partial_skip_full_close",
                          ref=trade["trade_ref"], units=units, units_to_close=units_to_close)
                continue

            _log.info("POSITION", "partial_triggered", ref=trade["trade_ref"], side=side,
                      entry=entry, tp=tp, target=partial_target, units=units,
                      units_to_close=units_to_close,
                      current=price["bid"] if side == "LONG" else price["ask"])

            result = close_partial_trade(oid, units_to_close, instrument="BCO_USD")

            if not result.get("success"):
                _log.error("BROKER", "partial_close_failed", ref=trade["trade_ref"],
                           units_to_close=units_to_close, err=result.get("error", "Unknown"))
                _log_journal_safe(trade["trade_ref"], "alpha_sweep_oil", "PARTIAL_TP_FAILED", None, {
                    "units_to_close": units_to_close,
                    "error": result.get("error"),
                    "retcode": result.get("retcode"),
                })
                continue

            fill_price = float(result.get("close_price") or partial_target)
            closed_units = int(result.get("closed_units") or units_to_close)
            remaining_units = int(result.get("remaining_units") or (units - units_to_close))
            # Banked P&L per unit, signed by side
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

            _log_journal_safe(trade["trade_ref"], "alpha_sweep_oil", "PARTIAL_TP", fill_price, {
                "side": side, "entry": entry, "tp": tp, "target": partial_target,
                "closed_units": closed_units, "remaining_units": remaining_units,
                "banked_usd": banked_usd, "partial_at_pct": partial_at, "partial_size": partial_sz,
            })

            try:
                notify.partial_tp(trade["trade_ref"], "BCO_USD", closed_units, fill_price,
                                  banked_usd, remaining_units)
            except Exception as e:
                print(f"  [OIL] notify.partial_tp swallowed exception: {e}")

            print(f"  [OIL] PARTIAL_TP {trade['trade_ref']} {side}: closed {closed_units}/{units} @ "
                  f"{fill_price:.4f}, banked ${banked_usd:+.2f}, runner={remaining_units}")
        except Exception as e:
            _log.exception("SYSTEM", "partial_check_loop_error",
                           ref=trade.get("trade_ref"), err=str(e))


def reconcile_orphans():
    """Adopt any broker positions that don't have a matching DB row.
    Production safety net for Oil Macro. See backend-oil-micro for full docs."""
    try:
        broker_open = get_open_trades(instrument="BCO_USD") or []
    except Exception as e:
        _log.exception("SYSTEM", "reconcile_get_open_trades_failed", err=str(e))
        print(f"  [OIL] reconcile_orphans: get_open_trades failed: {e}")
        return

    _log.debug("POSITION", "reconcile_tick", broker_open=len(broker_open))
    if not broker_open:
        # Issue #16 fix 2026-06-15: smell detector
        try:
            # Filter #27: exclude pending limits from "DB-open" smell count.
            # Pending rows correctly have no broker position (broker has a
            # pending order, not a position). Counting them here triggers
            # false-alarm "reconcile_empty_but_db_has_open" warnings.
            db_open = execute(
                "SELECT COUNT(*) as cnt FROM gd_trades WHERE exit_time IS NULL "
                "AND strategy = 'alpha_sweep_oil' AND COALESCE(mode, 'live') != 'pending'",
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
    # Filter #27: exclude pending limits — their oanda_trade_id is a pending
    # ticket, not a position, so the orphan reconciler must NOT try to match
    # it against `broker_open` (which only contains filled positions).
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
        lot_size = units / 1000.0  # oil: 1 lot = 1000 barrels

        trade_ref = f"OIL-AS-orphan-{broker_id[-8:]}"
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
                (trade_ref, "alpha_sweep_oil", side, entry_price,
                 sl, tp, lot_size, units, broker_id),
                fetch=True
            )
        except Exception as e:
            _log.exception("DB", "orphan_adopt_insert_failed", broker_id=broker_id, trade_ref=trade_ref, err=str(e))
            print(f"  [OIL] reconcile_orphans: INSERT failed for {broker_id}: {e}")
            _log_journal_safe("SYSTEM", "alpha_sweep_oil", "ORPHAN_ADOPT_FAILED",
                              entry_price, {"broker_id": broker_id, "error": str(e)})
            continue

        if not inserted:
            _log.debug("POSITION", "orphan_adopt_conflict_no_insert", broker_id=broker_id, trade_ref=trade_ref)
            continue

        _log.warn("POSITION", "orphan_adopted", trade_ref=trade_ref, broker_id=broker_id, side=side, units=units, entry=entry_price, sl=sl, tp=tp)
        _log_journal_safe(trade_ref, "alpha_sweep_oil", "ORPHAN_ADOPTED",
                          entry_price, {
                              "broker_id": broker_id, "side": side, "units": units,
                              "sl": sl, "tp": tp, "reason": "broker_position_not_in_db",
                          })

        try:
            notify.orphan_adopted(trade_ref, broker_id, "BCO_USD", side, units, entry_price, sl, tp)
        except Exception as e:
            _log.exception("SYSTEM", "orphan_notify_failed", trade_ref=trade_ref, err=str(e))
            print(f"  [OIL] reconcile_orphans: notify failed: {e}")

        print(f"  [OIL] ORPHAN ADOPTED: {trade_ref} (broker {broker_id}) — investigate logs")


# ---- Filter #27: pending-order monitor ----
# Periodic job (scheduler.py runs it every 30s) that reconciles each
# mode='pending' DB row against three EA-written files:
#   - DWX/pending_orders.json   (currently-pending limits)
#   - DWX/open_orders.json      (filled positions)
#   - DWX/cancelled_orders.json (recent cancellations from OnTradeTransaction)
# State machine for each pending row:
#   - ticket in pending_orders.json   → still pending, do nothing
#   - ticket in open_orders.json      → broker filled → flip mode='live',
#                                       update entry_time + entry_price
#                                       to actual broker fill
#   - ticket in cancelled_orders.json → TTL expired or manual cancel →
#                                       mark exit_time + LIMIT_TTL_EXPIRED
#   - ticket in NONE of the three     → orphan / file race; leave for
#                                       daily recon. Don't change DB row.

import json as _json  # local import to avoid top-of-file change


# Filter #27 grace fallback (Fix B for BUG_FILTER_27_PENDING_RECONCILER_GAP):
# If a pending ticket vanishes from all DWX files (orphan branch) AND its TTL
# elapsed PENDING_GRACE_SECONDS ago, treat as TTL_EXPIRED. Catches the broker-
# silent-expire path where OnTradeTransaction never fires because the broker
# auto-cancelled the order without notifying the MT5 client.
PENDING_GRACE_SECONDS = 60

# Telegram throttle: alert once per orphan ticket. Cleared when ticket finally
# resolves (filled / expired / cleanup) — see _resolve_orphan_state.
_orphan_alerted: set = set()

# M13: per-ticket counter of consecutive bad-open_price cycles in fill detection.
# H4 (skip cycle on missing/zero/None) protects against transient DWX mid-write
# races. M13 escalates if data stays bad for N cycles → indicates EA bug or
# stuck state. After escalation, sentinel value (-1) suppresses re-fire.
_bad_open_price_cycles: dict = {}
BAD_OPEN_PRICE_THRESHOLD = 5  # 5 × 30s = ~2.5 min before escalation


def _read_dwx_json(filename: str):
    """Read a DWX JSON file (best-effort, returns None on any error)."""
    from backend.execution.mt5_executor import DWX_DIR  # late import to keep cycle-free
    import os.path
    path = os.path.join(DWX_DIR, filename)
    try:
        with open(path, "r") as f:
            return _json.load(f)
    except Exception:
        return None


def _orphan_lookup_ttl_seconds(trade_ref: str) -> Optional[int]:
    """Pull ttl_seconds for an orphaned pending row, with config fallback.

    Lookup order:
      1. Most recent LIMIT_PLACED journal event for this trade_ref (canonical)
      2. ALPHA_SWEEP['limit_ttl_bars'] * 180 from config (fallback — H3 fix)

    Why the fallback matters (H3, 2026-06-17):
    Without a TTL value, the caller's grace check (`past_grace = elapsed >
    ttl_seconds + PENDING_GRACE_SECONDS`) silently evaluates False forever
    when ttl_seconds is None. Result: orphaned DB row never resolves, blocks
    new signals via one-at-a-time guard. Three failure modes that can produce
    None today:
      a) DB hiccup at the exact moment of lookup (every-30s monitor tick)
      b) LIMIT_PLACED journal write was swallowed upstream (rare but possible)
      c) Old pre-fix-B row exists with no journal event

    Production data (verified 2026-06-17): all 4 historical limit-path trades
    have LIMIT_PLACED journal events. Bug class is theoretical so far. The
    fallback is defense-in-depth for the day a DB hiccup races the lookup.

    Returns:
        int (ttl_seconds) — never None as long as ALPHA_SWEEP config is loaded
        None — only if the config import itself failed (pathological)
    """
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

    # Path 2: config fallback. ALPHA_SWEEP['limit_ttl_bars'] is the source of
    # truth for what ttl_seconds *would have been* at placement time. This
    # value is locked-in via Filter #27's BT-best variant ship config (Oil
    # Macro: ttl15 = 5 bars). If config has been live-modified since the
    # placement, the fallback is approximate but still correct order-of-mag.
    try:
        bars = ALPHA_SWEEP.get("limit_ttl_bars", 5)
        ttl_fallback = int(bars) * 180  # M3 = 180s/bar
        _log.info("BROKER", "orphan_ttl_lookup_config_fallback",
                  trade_ref=trade_ref, ttl_seconds=ttl_fallback,
                  source="ALPHA_SWEEP.limit_ttl_bars")
        return ttl_fallback
    except Exception as e:
        _log.exception("BROKER", "orphan_ttl_lookup_config_failed",
                       trade_ref=trade_ref, err=str(e),
                       note="even config fallback failed — orphan row will NOT resolve via grace")
        return None


def reconcile_broker_pending_orphans():
    """Filter #27 / C3 — find broker pending orders that have NO DB row.

    Race scenario this protects against:
      1. execute_signal calls place_limit_order
      2. EA processes OPEN_PENDING and the broker accepts the limit
      3. EA's last_response.json write is delayed > 10s
      4. Python's _send_command times out, returns success=False
      5. execute_signal sees failure, skips the DB INSERT
      6. Broker now has a pending limit at our magic with NO DB row
      7. If it fills: existing reconcile_orphans (filled-case) adopts it ✓
      8. If it expires: NOBODY ever knows it existed — silent audit-trail loss

    Production evidence (verified 2026-06-17):
      - 0 limit-order timeouts to date
      - 1 market-order timeout ever (Jun 7, micro_alpha_sweep)
      - Race is theoretical but possible

    Strategy: CANCEL orphan pendings (Option A — safest). We have no signal
    context to adopt them properly (don't know sweep_key, intended sl/tp,
    or which strategy fired). Cancelling cleanly:
      - Eliminates broker exposure within seconds
      - Surfaces a clear journal event for postmortem
      - Costs 1 trade in the worst case (race-orphan that would have been valid)
    Per audit data: race rate ≈ 0/1000 limits in production. Cost of cancel is
    near-zero in expected value.

    Magic check ensures we only touch our own orders; manual MT5 trades are
    skipped. Idempotent: ticket already cancelled = no-op.
    """
    pending_file = _read_dwx_json("pending_orders.json") or {}
    if not isinstance(pending_file, dict) or not pending_file:
        return  # No broker pendings = nothing to reconcile

    # All ticket IDs the DB knows about — cheap query, runs every 30s
    db_known = execute(
        "SELECT oanda_trade_id FROM gd_trades WHERE oanda_trade_id IS NOT NULL "
        "AND exit_time IS NULL",
        fetch=True
    ) or []
    db_known_tickets = {str(r["oanda_trade_id"]) for r in db_known}

    # Magic from config — only adopt OUR pendings, never manual MT5 trades
    OUR_MAGIC = 200000

    for ticket_str, info in pending_file.items():
        if not isinstance(info, dict):
            continue
        ticket = str(ticket_str)
        if ticket in db_known_tickets:
            continue  # known to us — handled by pending_order_monitor flow

        magic = info.get("magic")
        try:
            if int(magic) != OUR_MAGIC:
                continue  # not our order — manual MT5 trade
        except (TypeError, ValueError):
            continue  # malformed magic field — leave alone

        # Found a pending limit at our magic with NO DB row → race-orphan.
        # Cancel cleanly to eliminate broker exposure.
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

        # Journal the cancel attempt regardless of outcome
        synthetic_ref = f"OIL-AS-orphan-pend-{ticket[-8:]}"
        _log_journal_safe(synthetic_ref, "alpha_sweep_oil",
                          "LIMIT_ORPHAN_PENDING_CANCELLED",
                          float(price) if price else 0, {
                              "instrument": "BCO_USD",
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
    """Filter #27 periodic reconciler for mode='pending' rows.

    Runs every 30s via APScheduler. Idempotent — safe to run repeatedly. A
    fill detected on iteration N+1 is the same fill as on iteration N (DB
    has already been updated to mode='live'); the loop simply finds no
    pending rows for that ticket on iteration N+1.

    Race awareness:
    - Cancel-vs-fill race: if a limit fills the same instant our cancel
      command arrives, the broker may report success on the fill (writes
      to closed_orders.json eventually) AND fail the cancel (already
      filled). We detect via open_orders.json — that is the authoritative
      "is it a position now?" signal.
    - File-write race: DWX EA writes pending_orders.json + open_orders.json
      every poll cycle (~25ms). Reading them between two writes can show
      a ticket in NEITHER file briefly (during the transition tick). We
      handle this by treating that case as "orphan, leave DB row alone"
      — next iteration (30s later) will see a stable state.
    - Broker silent expire: JustMarkets sometimes auto-expires pending
      orders via ORDER_TIME_SPECIFIED without sending the MT5 client a
      TRADE_TRANSACTION_ORDER_DELETE notification. EA poll detects the
      ticket disappeared but can't write cancelled_orders.json without
      the OnTradeTransaction event. PENDING_GRACE_SECONDS fallback below
      catches this case; see docs/BUG_FILTER_27_PENDING_RECONCILER_GAP.md
    """
    # C3: also reconcile broker-side pendings with no DB row (race-timeout
    # orphans). Runs unconditionally — does not depend on pending_db being
    # populated. See reconcile_broker_pending_orphans for full rationale.
    try:
        reconcile_broker_pending_orphans()
    except Exception as e:
        _log.exception("BROKER", "reconcile_broker_pending_orphans_failed", err=str(e))

    pending_db = execute(
        "SELECT * FROM gd_trades WHERE exit_time IS NULL "
        "AND strategy='alpha_sweep_oil' AND COALESCE(mode, 'live') = 'pending'",
        fetch=True
    )
    if not pending_db:
        return

    pending_file = _read_dwx_json("pending_orders.json") or {}
    open_file = _read_dwx_json("open_orders.json") or {}
    cancelled_file = _read_dwx_json("cancelled_orders.json") or []
    # cancelled_orders.json is a JSON array of dicts. M9: keep state +
    # detected_via metadata so the LIMIT_TTL_EXPIRED journal can record
    # which path resolved the cancel:
    #   state         = "EXPIRED" | "CANCELED" | "EXPIRED_POLLED" | "CANCELED_POLLED"
    #   detected_via  = "ontradetrans" (EA OnTradeTransaction) | "poll" (Fix A)
    # Dict key (ticket) still supports `if ticket in cancelled_tickets`.
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
            # Still pending. Nothing to do.
            continue

        if ticket in open_tickets:
            # Broker filled. Pull the actual fill price + time from open_orders.json.
            fill_info = open_file.get(ticket, {})
            # H4 (2026-06-17): validate open_price before using. Three failure
            # modes the old `.get("open_price", intended_limit)` silently
            # collapsed into one bad path:
            #   1. missing field → defaulted to intended_limit (silent drift)
            #   2. open_price=0 → DB entry_price=$0 (garbage state)
            #   3. open_price=None → float(None) would crash
            # All three indicate DWX is mid-write or wrote bad data. Safest
            # response: skip THIS cycle and retry next monitor tick (30s).
            # See docs/FILTER_27_AUDIT_BACKLOG.md H4.
            raw_open_price = fill_info.get("open_price")
            if raw_open_price is None or float(raw_open_price) <= 0:
                # M13 — escalate persistent bad data. H4 alone retries forever
                # silently if DWX writes bad data persistently (EA bug, file
                # corruption, stuck state). Per-ticket counter; after N cycles
                # fire Telegram + force-cancel + mark row exit_reason so
                # operator hears about it before grace path masks it.
                prev_count = _bad_open_price_cycles.get(ticket, 0)
                if prev_count == -1:
                    # Already escalated — drop log noise but stay skipped this cycle
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
                                          "instrument": "BCO_USD", "ticket": ticket,
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
                            trade_ref, "BCO_USD", ticket,
                            intended_limit, bad_count, raw_open_price,
                        )
                    except Exception as e:
                        _log.exception("BROKER", "bad_open_price_notify_failed",
                                       trade_ref=trade_ref, err=str(e))
                    _bad_open_price_cycles[ticket] = -1  # sentinel: don't re-escalate
                    _orphan_alerted.discard(ticket)
                continue  # skip this row this cycle; next 30s tick should see complete data
            actual_fill = float(raw_open_price)
            # M13: clear bad-data counter on valid fill (transient resolved cleanly)
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
            # O4 — compute fill latency from row.entry_time (placement) to
            # broker_open_time (fill). Render compactly ("45s" / "7m12s").
            from backend.execution.mt5_executor import compute_time_to_fill
            time_to_fill = compute_time_to_fill(row["entry_time"], broker_open_time)
            _log.info("BROKER", "limit_filled", trade_ref=trade_ref, ticket=ticket,
                      intended_limit=intended_limit, actual_fill=actual_fill,
                      broker_open_time=broker_open_time, time_to_fill=time_to_fill)
            _log_journal_safe(trade_ref, row["strategy"], "LIMIT_FILLED", actual_fill, {
                "instrument": "BCO_USD", "ticket": ticket,
                "intended_limit": intended_limit, "actual_fill": actual_fill,
                "broker_open_time": broker_open_time, "time_to_fill": time_to_fill,
            })
            try:
                notify.trade_filled(trade_ref, "BCO_USD", row["side"].lower(),
                                    actual_fill, row["units"],
                                    float(row["sl_price"]),
                                    float(row["tp_price"]) if row["tp_price"] else 0)
            except Exception as e:
                _log.exception("BROKER", "limit_filled_notify_failed",
                               trade_ref=trade_ref, err=str(e))
            _orphan_alerted.discard(ticket)
            print(f"  [OIL] LIMIT FILLED: {trade_ref} ticket={ticket} @ ${actual_fill:.4f}")
            continue

        if ticket in cancelled_tickets:
            # TTL expired or manual cancel. Mark closed.
            # M9: surface EA's state + detected_via in journal context so
            # postmortem can distinguish OnTradeTransaction-caught (expected)
            # from poll-caught (Fix A; signals broker silent-expire).
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
                                  "instrument": "BCO_USD", "ticket": ticket,
                                  "intended_limit": intended_limit,
                                  "state": cancel_meta.get("state", ""),
                                  "detected_via": cancel_meta.get("detected_via", "ontradetrans"),
                              })
            try:
                notify.limit_ttl_expired(trade_ref, "BCO_USD", intended_limit)
            except Exception as e:
                _log.exception("BROKER", "limit_ttl_notify_failed",
                               trade_ref=trade_ref, err=str(e))
            _orphan_alerted.discard(ticket)
            print(f"  [OIL] LIMIT EXPIRED: {trade_ref} ticket={ticket} @ ${intended_limit:.4f}")
            continue

        # Orphan: ticket not in any of the 3 files. Could be:
        # - DWX file-write race (EA hasn't written yet for this tick)
        # - Broker auto-cancelled the order on TTL silently (no
        #   OnTradeTransaction event — confirmed seen on JustMarkets
        #   2026-06-17 with GD-MI-1e53d69b)
        # - Manual broker-side intervention
        #
        # Fix B: if TTL+grace has elapsed, resolve as TTL_EXPIRED. Otherwise
        # leave alone for next iteration. Fix C: throttled Telegram alert
        # once per ticket.
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
                                  "instrument": "BCO_USD", "ticket": ticket,
                                  "intended_limit": intended_limit,
                                  "exit_reason": "LIMIT_TTL_EXPIRED_GRACE",
                                  "elapsed_seconds": int(elapsed),
                                  "ttl_seconds": ttl_seconds,
                                  "fallback": "fix_b_grace",
                              })
            try:
                # M10: distinct Telegram suffix for grace fallback path so
                # operator distinguishes broker silent-expire (Fix B) from
                # broker normal-cancel on the phone, no SSH grep needed.
                notify.limit_ttl_expired(trade_ref, "BCO_USD", intended_limit,
                                         via_grace=True)
            except Exception as e:
                _log.exception("BROKER", "limit_ttl_grace_notify_failed",
                               trade_ref=trade_ref, err=str(e))
            _orphan_alerted.discard(ticket)
            print(f"  [OIL] LIMIT EXPIRED (grace fallback): {trade_ref} ticket={ticket} @ ${intended_limit:.4f}")
            continue

        # Within grace window: log warn + throttled Telegram (1× per ticket)
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
                                  "instrument": "BCO_USD", "ticket": ticket,
                                  "intended_limit": intended_limit,
                                  "elapsed_seconds": int(elapsed),
                                  "ttl_seconds": ttl_seconds,
                                  "note": "ticket missing from pending/open/cancelled; within grace",
                              })
            try:
                notify.limit_orphan_warn(trade_ref, "BCO_USD", ticket,
                                         intended_limit, int(elapsed))
            except Exception as e:
                _log.exception("BROKER", "orphan_alert_notify_failed",
                               trade_ref=trade_ref, err=str(e))
