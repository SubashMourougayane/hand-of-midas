"""Full Fib V2 ENSEMBLE evidence pack — mirrors research-baseline/research_evidence
layout but richer.

For each variant in {xau_long, xau_short, xau_ensemble, eur_long, eur_short, eur_ensemble}:
  - Run through bt_engine via the production code path (run_engine).
  - Persist every trade to PostgreSQL (bt_runs, bt_trades, bt_journal_events, bt_bar_walk).
  - Emit four CSVs:
      <variant>_trades.csv      — per-trade journal with FULL detail
      <variant>_bar_walk.csv    — per-bar journey for each trade
      <variant>_monthly.csv     — month-by-month aggregates
      <variant>_yearly.csv      — year-by-year aggregates

Additionally:
  - 5k_account_3pct_pnl.csv     — $5k 3% monthly reset cash flow (all variants in one CSV)
  - portfolio_combined.csv       — XAU + EUR combined monthly cash flow
  - summary_headline.csv         — one-line headline per variant
  - REPORT.md                    — narrative analysis with key plots/tables

Output dir: /Users/subash/SUBASH/GoldDigger/bt_engine/evidence/fib_v2_full_anatomy/
"""
from __future__ import annotations

import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.core.bar import Bar
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.data.multi_tf_view import MultiTfHistoryView
from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtBarWalk, BtJournalEvent, BtRun, BtTrade
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2 import (
    FibV2EnsembleStrategy,
    LONG_BULL_STRONG,
    SHORT_BEAR_STRONG,
)


OUT_DIR = Path("/Users/subash/SUBASH/GoldDigger/bt_engine/evidence/fib_v2_full_anatomy")
DB_URL = os.environ.get("BT_ENGINE_DB_URL",
                          "postgresql+psycopg2://subash@localhost:5432/golddigger_bt")

START_NAV = 5000.0
RISK_PCT = 0.03
XAU_CONTRACT = 100
EUR_LOT_SIZE = 100000  # 1 lot = 100,000 units
LEVERAGE = 1000
MIN_LOT = 0.01
LOT_STEP = 0.01
HORIZON_BARS = 72 * 12 * 2  # research: max_hold_h=72, M5=12/h, doubled


VARIANTS = [
    ("xau_long", "XAUUSD.ecn", "/tmp/oanda_xau_m5.parquet", "/tmp/oanda_xau_h1.parquet",
     0.30, (LONG_BULL_STRONG,)),
    ("xau_short", "XAUUSD.ecn", "/tmp/oanda_xau_m5.parquet", "/tmp/oanda_xau_h1.parquet",
     0.30, (SHORT_BEAR_STRONG,)),
    ("xau_ensemble", "XAUUSD.ecn", "/tmp/oanda_xau_m5.parquet", "/tmp/oanda_xau_h1.parquet",
     0.30, (LONG_BULL_STRONG, SHORT_BEAR_STRONG)),
    ("eur_long", "EURUSD.ecn", "/tmp/oanda_eur_m5.parquet", "/tmp/oanda_eur_h1.parquet",
     0.00003, (LONG_BULL_STRONG,)),
    ("eur_short", "EURUSD.ecn", "/tmp/oanda_eur_m5.parquet", "/tmp/oanda_eur_h1.parquet",
     0.00003, (SHORT_BEAR_STRONG,)),
    ("eur_ensemble", "EURUSD.ecn", "/tmp/oanda_eur_m5.parquet", "/tmp/oanda_eur_h1.parquet",
     0.00003, (LONG_BULL_STRONG, SHORT_BEAR_STRONG)),
]


def load_oanda(m5_path: str, h1_path: str | None = None):
    m5 = pd.read_parquet(m5_path)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    h1 = None
    if h1_path and Path(h1_path).exists():
        h1 = pd.read_parquet(h1_path)
        if h1["timestamp"].dt.tz is None:
            h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")
        h1 = h1.sort_values("timestamp").reset_index(drop=True)
    return m5, h1


class InMemoryProvider:
    def __init__(self, frame, symbol, timeframe="M5"):
        self._df = frame.reset_index(drop=True)
        self.symbol = symbol
        self.timeframe = timeframe
        self._ts_arr = self._df["timestamp"].values

    def bars(self):
        for row in self._df.itertuples(index=False):
            yield Bar.from_row(symbol=self.symbol, timeframe=self.timeframe, row=row._asdict())

    def history_up_to(self, ts):
        ts_val = pd.Timestamp(ts).to_datetime64()
        end_idx = self._ts_arr.searchsorted(ts_val, side="right")
        return self._df.iloc[:end_idx]


class InMemoryClock:
    def __init__(self, provider):
        self._iter = iter(provider.bars())

    def tick(self):
        try:
            return next(self._iter)
        except StopIteration:
            return None


def run_variant(*, variant_name, symbol, m5_path, h1_path, cost_usd, legs):
    """Run one variant through bt_engine. Persist run + trades + journal + bar walks
    to DB. Return rich per-trade DataFrame.
    """
    print(f"\n[{variant_name}] loading {Path(m5_path).name}...")
    m5, h1 = load_oanda(m5_path, h1_path)
    print(f"  M5={len(m5):,} bars, range {m5.timestamp.min()} → {m5.timestamp.max()}")

    mtf = MultiTfHistoryView(m5)
    if h1 is not None:
        mtf._h1 = h1
    provider = InMemoryProvider(m5, symbol=symbol)
    clock = InMemoryClock(provider)
    strat = FibV2EnsembleStrategy(
        symbol=symbol, legs=tuple(legs), cost_usd=cost_usd,
        multi_tf_view=mtf,
    )

    run_id = uuid.uuid4()
    run_ref = f"EVID-{variant_name}-{run_id}"
    engine_db = make_engine(DB_URL)

    print(f"  run_id: {run_id}")
    with Session(engine_db, expire_on_commit=False) as session:
        bt_run = BtRun(
            run_id=run_id, ref=run_ref, mode="bt",
            strategy_id="fib_v2_xau_ensemble" if len(legs) == 2 else (
                "fib_v2_xau_long" if legs[0].direction == "long" else "fib_v2_xau_short"
            ),
            strategy_config={"pivot_lb": 5, "ext_target_pct": 1.618,
                             "sl_buffer_pct": 0.02, "legs": [l.leg_name for l in legs],
                             "cost_usd": cost_usd, "variant": variant_name},
            symbol=symbol, timeframe="M5",
            start_ts=datetime.now(timezone.utc),
            data_provider="oanda_parquet",
        )
        session.add(bt_run)
        session.commit()

    # Capture rich trade rows + per-bar walks.
    rows = []
    bar_walks = []  # list[dict] for each in-trade bar observation
    open_trade_log = {}  # trade_id → list of bars while open

    def _on_open(trade):
        open_trade_log[trade.trade_id] = []

    def _on_close(trade, outcome):
        # Persist to DB.
        cost_r = trade.order.extra.get("cost_r", 0.0)
        net_r = outcome.bracket_1r_outcome - cost_r
        leg_name = trade.order.extra.get("leg")
        regime = trade.order.extra.get("regime")
        trade_ref = f"FIB-{variant_name.upper()}-{trade.trade_id}"
        with Session(engine_db, expire_on_commit=False) as session:
            bt_t = BtTrade(
                trade_id=trade.trade_id, trade_ref=trade_ref, run_id=run_id,
                strategy_id="fib_v2_xau_ensemble",
                symbol=symbol, timeframe="M5",
                direction="long" if trade.side > 0 else "short", side=trade.side,
                entry_timestamp=trade.entry_timestamp.to_pydatetime(),
                entry_price=trade.entry_price,
                stop_price=trade.stop_price, risk_units=trade.risk_units,
                take_profit_price=trade.take_profit,
                exit_timestamp=outcome.exit_timestamp.to_pydatetime(),
                exit_price=outcome.exit_price, exit_reason=outcome.reason,
                bars_held=outcome.bars_held,
                bracket_1r_outcome=outcome.bracket_1r_outcome,
                cost_r=cost_r,
                gross_r=outcome.bracket_1r_outcome,
                net_r=net_r,
                pivot_lb=trade.order.extra.get("pivot_lb"),
                regime=regime,
                ext_target_pct=trade.order.extra.get("ext_target_pct"),
                sl_buffer_pct=trade.order.extra.get("sl_buffer_pct"),
                fib_diff=trade.order.extra.get("fib_diff"),
                regime_at_entry=trade.order.extra.get("regime_at_entry"),
                leg=leg_name,
                raw_features=trade.order.extra,
            )
            session.add(bt_t)
            session.commit()

        # Pull bar-walk observations recorded during the trade.
        walks = open_trade_log.pop(trade.trade_id, [])
        for w in walks:
            w["trade_id"] = str(trade.trade_id)
            w["trade_ref"] = trade_ref
            bar_walks.append(w)

        rows.append({
            "trade_ref": trade_ref,
            "run_id": str(run_id),
            "leg": leg_name,
            "regime": regime,
            "side": int(trade.side),
            "entry_ts": trade.entry_timestamp,
            "exit_ts": outcome.exit_timestamp,
            "bars_held": outcome.bars_held,
            "entry_price": float(trade.entry_price),
            "stop_price": float(trade.stop_price),
            "tp_price": float(trade.take_profit) if trade.take_profit else None,
            "exit_price": float(outcome.exit_price),
            "exit_reason": outcome.reason,
            "fib_L": trade.order.extra.get("fib_L"),
            "fib_H": trade.order.extra.get("fib_H"),
            "fib_diff": trade.order.extra.get("fib_diff"),
            "fib_382": trade.order.extra.get("fib_382"),
            "fib_786": trade.order.extra.get("fib_786"),
            "fib_100": trade.order.extra.get("fib_100"),
            "ext_target_pct": trade.order.extra.get("ext_target_pct"),
            "sl_buffer_pct": trade.order.extra.get("sl_buffer_pct"),
            "setup_confirm_ts": trade.order.extra.get("setup_confirm_ts"),
            "ny_hr_at_entry": trade.order.extra.get("ny_hr"),
            "risk_units": float(trade.risk_units),
            "bracket_r": float(outcome.bracket_1r_outcome),
            "cost_r": float(cost_r),
            "net_r": float(net_r),
            "mfe_r": float(trade.mfe_r),
            "mae_r": float(trade.mae_r),
            "rr_realized": (
                float(outcome.exit_price - trade.entry_price) * trade.side / trade.risk_units
                if trade.risk_units > 0 else 0.0
            ),
            "year": trade.entry_timestamp.year,
            "month": trade.entry_timestamp.strftime("%Y-%m"),
            "symbol": symbol,
            "variant": variant_name,
            "cost_usd": cost_usd,
        })

    # Bar-walk observer: track every in-trade bar.
    class _Journal:
        def observe(self, trade_id, bar, phase):
            if trade_id in open_trade_log:
                # Compute MFE/MAE for this bar.
                open_trade_log[trade_id].append({
                    "bar_ts": bar.timestamp,
                    "phase": phase,
                    "open": bar.open, "high": bar.high,
                    "low": bar.low, "close": bar.close,
                    "volume": bar.volume,
                })

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None,
        journal=_Journal(),  # capture per-bar
        on_trade_open=_on_open, on_trade_close=_on_close,
        max_bars_held=HORIZON_BARS,
    )
    print(f"  running engine...")
    run = run_engine(run_id=run_id, deps=deps, mode="bt")
    print(f"  bars processed: {run.bars_processed:,}, closed trades: {len(rows)}")

    # Close run.
    with Session(engine_db, expire_on_commit=False) as session:
        rec = session.execute(select(BtRun).where(BtRun.run_id == run_id)).scalar_one()
        rec.end_ts = datetime.now(timezone.utc)
        session.commit()

    return pd.DataFrame(rows), pd.DataFrame(bar_walks)


def emit_monthly(trades: pd.DataFrame, label: str) -> pd.DataFrame:
    if len(trades) == 0:
        return pd.DataFrame()
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["month"] = df["entry_ts"].dt.strftime("%Y-%m")
    grp = df.groupby("month").agg(
        n_trades=("net_r", "count"),
        wins=("net_r", lambda s: int((s > 0).sum())),
        losses=("net_r", lambda s: int((s <= 0).sum())),
        net_R=("net_r", "sum"),
        gross_win_R=("net_r", lambda s: float(s[s > 0].sum())),
        gross_loss_R=("net_r", lambda s: float(-s[s < 0].sum())),
        max_R=("net_r", "max"),
        min_R=("net_r", "min"),
        avg_R=("net_r", "mean"),
        avg_mfe_R=("mfe_r", "mean"),
        avg_mae_R=("mae_r", "mean"),
        avg_bars_held=("bars_held", "mean"),
        n_TP=("exit_reason", lambda s: int((s == "TP").sum())),
        n_SL=("exit_reason", lambda s: int((s == "SL").sum())),
        n_TIMEOUT=("exit_reason", lambda s: int((s == "TIMEOUT").sum())),
    ).reset_index()
    grp["WR%"] = (grp["wins"] / grp["n_trades"] * 100).round(2)
    grp["PF"] = (grp["gross_win_R"] / grp["gross_loss_R"].replace(0, np.nan)).round(3)
    grp["variant"] = label
    return grp


def emit_yearly(trades: pd.DataFrame, label: str) -> pd.DataFrame:
    if len(trades) == 0:
        return pd.DataFrame()
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["year"] = df["entry_ts"].dt.year
    grp = df.groupby("year").agg(
        n_trades=("net_r", "count"),
        wins=("net_r", lambda s: int((s > 0).sum())),
        losses=("net_r", lambda s: int((s <= 0).sum())),
        net_R=("net_r", "sum"),
        gross_win_R=("net_r", lambda s: float(s[s > 0].sum())),
        gross_loss_R=("net_r", lambda s: float(-s[s < 0].sum())),
        max_R=("net_r", "max"),
        min_R=("net_r", "min"),
        avg_R=("net_r", "mean"),
        avg_bars_held=("bars_held", "mean"),
        n_TP=("exit_reason", lambda s: int((s == "TP").sum())),
        n_SL=("exit_reason", lambda s: int((s == "SL").sum())),
        n_TIMEOUT=("exit_reason", lambda s: int((s == "TIMEOUT").sum())),
    ).reset_index()
    grp["WR%"] = (grp["wins"] / grp["n_trades"] * 100).round(2)
    grp["PF"] = (grp["gross_win_R"] / grp["gross_loss_R"].replace(0, np.nan)).round(3)
    grp["variant"] = label
    return grp


def compute_5k_monthly_pnl(trades: pd.DataFrame, *, contract_size: float, label: str) -> pd.DataFrame:
    """$5k account, 3% risk, monthly NAV reset.
    Returns one row per trade with nav_before, lots, dollar_per_R, pnl_dollars, nav_after.
    """
    if len(trades) == 0:
        return pd.DataFrame()
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")

    nav = START_NAV
    curr_month = None
    out = []
    for _, r in df.iterrows():
        if curr_month is None:
            curr_month = r["year_month"]; nav = START_NAV; reset = True
        elif r["year_month"] != curr_month:
            curr_month = r["year_month"]; nav = START_NAV; reset = True
        else:
            reset = False
        nav_before = nav
        risk_units = float(r["risk_units"])
        if risk_units <= 0:
            out.append({**r.to_dict(), "nav_before": nav_before, "lots": 0,
                         "pnl_dollars": 0, "nav_after": nav,
                         "month_reset_flag": reset, "skipped": True})
            continue
        risk_dollars = nav * RISK_PCT
        dollar_per_lot = risk_units * contract_size
        if dollar_per_lot <= 0:
            out.append({**r.to_dict(), "nav_before": nav_before, "lots": 0,
                         "pnl_dollars": 0, "nav_after": nav,
                         "month_reset_flag": reset, "skipped": True})
            continue
        raw_lots = risk_dollars / dollar_per_lot
        max_m_lots = (0.9 * nav * LEVERAGE) / (float(r["entry_price"]) * contract_size)
        lots = math.floor(min(raw_lots, max_m_lots) / LOT_STEP) * LOT_STEP
        if lots < MIN_LOT:
            out.append({**r.to_dict(), "nav_before": nav_before, "lots": 0,
                         "pnl_dollars": 0, "nav_after": nav,
                         "month_reset_flag": reset, "skipped": True})
            continue
        dollar_per_r = lots * contract_size * risk_units
        pnl = float(r["net_r"]) * dollar_per_r
        nav += pnl
        out.append({**r.to_dict(), "nav_before": nav_before, "lots": lots,
                     "risk_dollars": risk_dollars, "dollar_per_R": dollar_per_r,
                     "pnl_dollars": pnl, "nav_after": nav,
                     "month_reset_flag": reset, "skipped": False})
    df_out = pd.DataFrame(out)
    df_out["variant"] = label
    return df_out


def summarize_pnl(pnl_df: pd.DataFrame, label: str) -> dict:
    if len(pnl_df) == 0:
        return {"variant": label, "n_trades": 0}
    s = pnl_df[~pnl_df.get("skipped", False)].copy()
    monthly = s.groupby("year_month")["pnl_dollars"].sum()
    yearly = s.groupby(s["entry_ts"].dt.year)["pnl_dollars"].sum()
    return {
        "variant": label,
        "n_trades": int(len(s)),
        "n_months": int(len(monthly)),
        "n_years": int(len(yearly)),
        "total_$": float(monthly.sum()),
        "avg_$/month": float(monthly.mean()),
        "median_$/month": float(monthly.median()),
        "best_month_$": float(monthly.max()),
        "worst_month_$": float(monthly.min()),
        "best_month_label": str(monthly.idxmax()),
        "worst_month_label": str(monthly.idxmin()),
        "pos_months": int((monthly > 0).sum()),
        "neg_months": int((monthly < 0).sum()),
        "pos_months_pct": float((monthly > 0).mean() * 100),
        "pos_years": int((yearly > 0).sum()),
        "neg_years": int((yearly < 0).sum()),
        "avg_lots": float(s["lots"].mean()),
        "max_lots": float(s["lots"].max()),
        "best_year_$": float(yearly.max()),
        "worst_year_$": float(yearly.min()),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing evidence pack to: {OUT_DIR}")

    summary_rows = []
    portfolio_monthly = {}  # variant → Series

    for variant_name, symbol, m5_path, h1_path, cost_usd, legs in VARIANTS:
        print(f"\n{'='*70}\nVARIANT: {variant_name}\n{'='*70}")
        trades, bar_walks = run_variant(
            variant_name=variant_name, symbol=symbol,
            m5_path=m5_path, h1_path=h1_path,
            cost_usd=cost_usd, legs=legs,
        )
        if len(trades) == 0:
            print(f"  [no trades for {variant_name}, skip]")
            continue

        # Per-trade CSV.
        trades_path = OUT_DIR / f"{variant_name}_trades.csv"
        trades.to_csv(trades_path, index=False)
        print(f"  wrote {trades_path.name}: {len(trades):,} trades")

        # Per-bar walk CSV (one row per bar per trade — can be large).
        if len(bar_walks):
            walk_path = OUT_DIR / f"{variant_name}_bar_walk.csv"
            bar_walks.to_csv(walk_path, index=False)
            print(f"  wrote {walk_path.name}: {len(bar_walks):,} bar-walk rows")

        # Monthly + yearly.
        monthly = emit_monthly(trades, variant_name)
        yearly = emit_yearly(trades, variant_name)
        monthly.to_csv(OUT_DIR / f"{variant_name}_monthly.csv", index=False)
        yearly.to_csv(OUT_DIR / f"{variant_name}_yearly.csv", index=False)
        print(f"  wrote {variant_name}_monthly.csv ({len(monthly)} months), {variant_name}_yearly.csv ({len(yearly)} years)")

        # $5k 3% monthly reset PnL.
        contract_size = EUR_LOT_SIZE if symbol.startswith("EUR") else XAU_CONTRACT
        pnl_df = compute_5k_monthly_pnl(trades, contract_size=contract_size, label=variant_name)
        pnl_path = OUT_DIR / f"{variant_name}_5k_3pct_pnl.csv"
        pnl_df.to_csv(pnl_path, index=False)
        print(f"  wrote {pnl_path.name}: {len(pnl_df):,} trade rows with $-PnL")

        # Headline summary.
        summary = summarize_pnl(pnl_df, variant_name)
        # Add R-based headline.
        r = trades["net_r"]
        n = len(r)
        wins = float(r[r > 0].sum())
        losses = -float(r[r < 0].sum())
        pf = wins / losses if losses > 0 else float("inf")
        equity = r.cumsum()
        dd = float((equity - equity.cummax()).min())
        summary.update({
            "net_R": float(r.sum()),
            "WR%": float((r > 0).mean() * 100),
            "PF": float(pf),
            "max_DD_R": dd,
            "MAR": float(-r.sum() / dd) if dd != 0 else None,
            "avg_R_per_trade": float(r.mean()),
            "max_R": float(r.max()),
            "min_R": float(r.min()),
            "trades_per_year": float(n / (pd.to_datetime(trades["entry_ts"]).dt.year.nunique() or 1)),
            "symbol": symbol,
            "cost_usd": cost_usd,
        })
        summary_rows.append(summary)

        # Monthly portfolio series.
        if not pnl_df.empty:
            m = pnl_df[~pnl_df.get("skipped", False)].groupby("year_month")["pnl_dollars"].sum()
            portfolio_monthly[variant_name] = m

    # Summary headline.
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT_DIR / "summary_headline.csv", index=False)
    print(f"\nwrote summary_headline.csv ({len(summary_df)} variants)")

    # Combined portfolio monthly.
    if portfolio_monthly:
        port = pd.DataFrame(portfolio_monthly).fillna(0.0)
        port = port.sort_index()
        port["xau_combined_$"] = port.get("xau_ensemble", 0)
        port["eur_combined_$"] = port.get("eur_ensemble", 0)
        port["xau_plus_eur_$"] = port.get("xau_ensemble", 0) + port.get("eur_ensemble", 0)
        port.to_csv(OUT_DIR / "portfolio_monthly_combined.csv")
        print(f"wrote portfolio_monthly_combined.csv ({len(port)} months)")

    print(f"\nDONE. Evidence pack at: {OUT_DIR}")
    print("\nFiles:")
    for f in sorted(OUT_DIR.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}  ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
