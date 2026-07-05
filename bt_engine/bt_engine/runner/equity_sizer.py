"""Model B 1.5% asymmetric monthly equity sizer.

100TH-TIME AUDIT CHECKLIST (per file):
  1. Equity reads ONLY from realized PnL (closed trades + current balance) — NO mark-to-market peek.
  2. risk_dollar = current_equity * risk_pct — computed at order-submit time, NOT at signal time.
  3. End-of-month: if equity > start → skim profit, reset to start. If equity < start → keep
     (eat losses, trade smaller next month).
  4. Wipe-out: if equity <= 0 → reject all orders until manual reload.
  5. NO LOOK-AHEAD: all updates triggered by closed trades, never by open trades or bars not closed.
  6. Time-zone: month boundaries in UTC (matches research convention).
  7. STATE persistence: sizer state is owned by the live runner, not the strategy. Single-threaded.

Sizing model:
  - Account starts at start_balance (e.g., $5,000).
  - Each trade risks risk_pct of CURRENT equity (recomputed per trade).
  - lot_size = risk_dollar / (stop_distance × oz_per_lot) for XAU/EUR.
  - End-of-month: skim profits OR keep underwater capital (asymmetric).

For XAU on JustMarkets: 1 lot = 100 oz. stop_distance in $ per oz.
For EUR on JustMarkets: 1 lot = 100,000 units. stop_distance in pips.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


log = logging.getLogger(__name__)


# Per-symbol contract size in base units per 1.0 lot.
# XAU: 1 lot = 100 oz, so risk_dollar = lot × 100 × stop_distance_$
# EUR: 1 lot = 100,000 units, so risk_dollar = lot × 100000 × stop_distance_$
# Add more symbols as needed.
CONTRACT_SIZE: dict[str, float] = {
    "XAUUSD": 100.0,
    "XAUUSD.ecn": 100.0,
    "EURUSD": 100_000.0,
    "EURUSD.ecn": 100_000.0,
    "GBPUSD": 100_000.0,
    "GBPUSD.ecn": 100_000.0,
}

# Minimum tradeable lot per broker spec
DEFAULT_MIN_LOT = 0.01
DEFAULT_LOT_STEP = 0.01


@dataclass
class EquitySizerState:
    """Mutable state owned by the live runner. NOT persisted across process restarts
    by this class — caller responsible for hydrating from DB on resume.

    current_month is None until the first size_order or on_trade_closed call —
    set to the ts of that first action. This avoids a spurious month-roll on
    init when seeded from datetime.now().
    """
    current_equity: float
    month_start_equity: float
    current_month: Optional[str] = None  # 'YYYY-MM' UTC; None until first action
    skim_history: list[dict] = field(default_factory=list)
    wiped: bool = False


@dataclass(frozen=True)
class EquitySizerConfig:
    """Production-locked config."""
    start_balance: float = 5000.0
    risk_pct: float = 0.015  # 1.5% per trade
    min_risk_units_xau: float = 0.50  # broker un-tradeable below this stop distance
    min_lot: float = DEFAULT_MIN_LOT
    lot_step: float = DEFAULT_LOT_STEP

    def __post_init__(self):
        if self.start_balance <= 0:
            raise ValueError("start_balance must be > 0")
        if not 0 < self.risk_pct < 1:
            raise ValueError("risk_pct must be in (0, 1)")
        if self.min_lot <= 0 or self.lot_step <= 0:
            raise ValueError("min_lot and lot_step must be > 0")


class EquitySizer:
    """Computes lot size per trade based on current equity + Model B monthly reset.

    Usage:
      sizer = EquitySizer(config=EquitySizerConfig())
      # On every order submit:
      lot = sizer.size_order(symbol="XAUUSD.ecn", stop_distance=2.5, ts=now_utc)
      # On every trade close:
      sizer.on_trade_closed(pnl_dollars=+150.0, close_ts=now_utc)
    """

    def __init__(self, config: EquitySizerConfig | None = None) -> None:
        self.config = config or EquitySizerConfig()
        # current_month=None → seeded on first action (avoid spurious init-time roll)
        self.state = EquitySizerState(
            current_equity=self.config.start_balance,
            month_start_equity=self.config.start_balance,
            current_month=None,
        )

    # ---------------- core API ----------------

    def size_order(self, *, symbol: str, stop_distance: float, ts: datetime) -> float:
        """Return lot size for an order. ts is the order-submit time (UTC).

        Causality: stop_distance comes from the strategy's Order.risk_units,
        which was computed from a CLOSED bar's open. No future peek.
        """
        if self.state.wiped:
            log.warning("[SIZER] account wiped — rejecting all orders until reload")
            return 0.0

        if stop_distance < self.config.min_risk_units_xau and symbol.upper().startswith("XAU"):
            log.warning("[SIZER] stop_distance %.4f < min %.4f for %s — rejecting",
                          stop_distance, self.config.min_risk_units_xau, symbol)
            return 0.0

        # End-of-month check FIRST (uses the order's ts, never future)
        self._roll_month_if_needed(ts)

        if self.state.current_equity <= 0:
            self.state.wiped = True
            log.error("[SIZER] equity <= 0 — wipe-out detected")
            return 0.0

        # Risk in dollars at THIS trade's submit time
        risk_dollar = self.state.current_equity * self.config.risk_pct

        # Convert to lots via symbol's contract size
        contract = CONTRACT_SIZE.get(symbol)
        if contract is None:
            raise ValueError(f"Unknown contract size for {symbol}. Add to CONTRACT_SIZE.")
        if stop_distance <= 0:
            log.warning("[SIZER] stop_distance <= 0, rejecting")
            return 0.0

        raw_lot = risk_dollar / (stop_distance * contract)
        # Round DOWN to nearest lot_step
        steps = int(raw_lot / self.config.lot_step)
        sized_lot = steps * self.config.lot_step
        if sized_lot < self.config.min_lot:
            log.info("[SIZER] computed lot %.4f < min_lot %.4f — rejecting",
                       sized_lot, self.config.min_lot)
            return 0.0

        log.info(
            "[SIZER] equity=%.2f risk_pct=%.4f risk_$=%.2f stop=%.4f contract=%s raw_lot=%.4f sized=%.4f",
            self.state.current_equity, self.config.risk_pct, risk_dollar,
            stop_distance, contract, raw_lot, sized_lot,
        )
        return sized_lot

    def on_trade_closed(self, *, pnl_dollars: float, close_ts: datetime) -> None:
        """Update equity with closed trade PnL. close_ts is the trade's exit ts.

        Causality: only CLOSED trades update equity. Open trades never read into
        sizing. Realized-only PnL model.
        """
        # Roll month boundaries BEFORE applying pnl (if close_ts crossed month)
        self._roll_month_if_needed(close_ts)
        self.state.current_equity += pnl_dollars
        log.info("[SIZER] trade closed: pnl=$%+.2f new_equity=$%.2f", pnl_dollars, self.state.current_equity)

    # ---------------- internals ----------------

    def _roll_month_if_needed(self, ts: datetime) -> None:
        """Check if ts crossed into a new month. If so, apply skim/keep logic.

        Model B asymmetric:
          - equity > start → skim profit, reset equity to start, record skim
          - equity <= start → keep equity, no reset (trade with what's left)
        """
        new_month = _month_key(ts)
        # First action: seed current_month, no roll
        if self.state.current_month is None:
            self.state.current_month = new_month
            return
        if new_month == self.state.current_month:
            return

        # Crossed a month boundary
        eq = self.state.current_equity
        start = self.config.start_balance
        skimmed = 0.0
        if eq > start:
            skimmed = eq - start
            self.state.current_equity = start
        # else: keep eq as-is (eat the loss, trade smaller next month)

        record = {
            "month_closed": self.state.current_month,
            "month_open": new_month,
            "equity_end": eq,
            "skim_amount": skimmed,
            "carry_forward": self.state.current_equity,
            "ts": ts.isoformat(),
        }
        self.state.skim_history.append(record)
        self.state.current_month = new_month
        self.state.month_start_equity = self.state.current_equity
        log.info(
            "[SIZER] month roll %s -> %s: end_eq=$%.2f skim=$%.2f carry=$%.2f",
            record["month_closed"], record["month_open"],
            eq, skimmed, self.state.current_equity,
        )

    # ---------------- restart hydration (F2) ----------------

    def hydrate_equity(self, broker_balance: float, *, source: str = "broker") -> bool:
        """Reset current_equity to the broker's REALIZED balance on live restart.

        F2: without this, every process restart re-seeds current_equity to
        config.start_balance (a fixed number, e.g. $10,000). After 43 restarts
        in 4 days the sizer risks 1.5% of a stale constant, not the real account
        — over-risking when the account grew, under-risking when it shrank.

        Broker `balance` (NOT equity) is the correct source: it is realized-only
        (closed trades + deposits), exactly matching the sizer's realized-PnL
        model — floating P&L must never feed sizing (no mark-to-market peek).

        Only hydrates a positive, finite balance; a bad read leaves the seed
        untouched (fail-safe). Does NOT touch current_month/skim_history — those
        re-seed correctly on the first post-restart action. Returns True if it
        applied a new equity value."""
        try:
            bal = float(broker_balance)
        except (TypeError, ValueError):
            return False
        if not (bal > 0 and bal == bal and bal != float("inf")):  # >0, not NaN/inf
            log.warning("[SIZER] hydrate skipped — implausible balance %r", broker_balance)
            return False
        old = self.state.current_equity
        self.state.current_equity = bal
        self.state.month_start_equity = bal
        log.info("[SIZER] hydrated equity from %s: $%.2f -> $%.2f", source, old, bal)
        return True

    # ---------------- inspection helpers ----------------

    def equity(self) -> float:
        return self.state.current_equity

    def lifetime_skim(self) -> float:
        return sum(r["skim_amount"] for r in self.state.skim_history)


def _month_key(ts: datetime) -> str:
    """UTC 'YYYY-MM' key. Causally safe — ts is the trade's timestamp."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    elif ts.tzinfo != timezone.utc:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m")
