"""Realistic PnL harness — post-hoc reality-adjustment on existing bt_trades.

Zero strategy code edits. Reads combined A+D BT run 2405209e (27,965 trades),
then replays each trade with realistic broker constraints:

  P0: per-lot cost model
      cost_$ = (commission_per_lot * qty) + (spread_$_per_lot * qty)
      Default: $6.50 commission + $9.00 spread = $15.50 / lot
      vs BT's flat $0.65 per trade → 24× more expensive at 1 lot

  P1: annual withdrawal simulation
      Every Jan 1: reset balance to $10k (skim excess into "cumulative_withdrawn")
      Reports total_withdrawn + final_balance = realistic take-home over 22yr

  P3: broker lot ceiling
      Model B sizer capped at max_lot (default 5.0 lots XAU)
      No more compound fantasy — position size levels off at ceiling

Also computes several alternative scenarios for comparison:
  - Baseline (as stored in DB)
  - Just P0 (per-lot cost only, keep compound sizing)
  - P0 + P3 (per-lot cost + lot ceiling, keep compound sizing)
  - P0 + P1 (per-lot cost + annual reset, no ceiling)
  - P0 + P1 + P3 (all three — RECOMMENDED realistic)
  - Fixed-$ sizing (every trade risks $150 flat, no Model B) — most honest floor

Outputs:
  - realistic_pnl/*.parquet per scenario
  - realistic_pnl/summary.csv with headline stats per scenario
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)
RUN_ID = "2405209e-8f08-462a-893d-1df822ebfbf2"
OUT_DIR = Path(__file__).parent

# ── Broker cost model (JustMarkets Raw Spread XAU) ─────────────────────
COMMISSION_PER_LOT_USD = 6.50   # round-turn ($3.25 open + $3.25 close)
SPREAD_USD_PER_LOT = 9.00       # ~$0.09 pip × 100 (contract size)
COST_PER_LOT_USD = COMMISSION_PER_LOT_USD + SPREAD_USD_PER_LOT  # $15.50 / lot
CONTRACT_SIZE_XAU = 100.0        # XAU 1 lot = 100 oz

# ── Sizer settings ──────────────────────────────────────────────────────
START_BALANCE = 10_000.0
RISK_PCT = 0.015
FIXED_RISK_USD = START_BALANCE * RISK_PCT  # $150

# ── Broker ceilings ─────────────────────────────────────────────────────
MAX_LOT = 5.0
MIN_LOT = 0.01


def load_trades() -> pd.DataFrame:
    eng = create_engine(DB_URL)
    q = text("""
        SELECT trade_id::text, entry_timestamp, exit_timestamp, direction, leg,
               entry_price, stop_price, take_profit_price, risk_units,
               bracket_1r_outcome as gross_r_bracket,
               partial_taken, partial_r, cost_r as bt_cost_r,
               (raw_features->>'fib_diff')::numeric as fib_diff
        FROM bt_trades WHERE run_id = :rid AND exit_timestamp IS NOT NULL
        ORDER BY entry_timestamp
    """)
    with eng.connect() as c:
        df = pd.read_sql(q, c, params={"rid": RUN_ID})
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    for c in ["entry_price", "stop_price", "take_profit_price", "risk_units",
              "gross_r_bracket", "partial_r", "bt_cost_r"]:
        df[c] = df[c].astype(float)
    df["partial_r"] = df["partial_r"].fillna(0.0)
    df["gross_r_bracket"] = df["gross_r_bracket"].fillna(0.0)
    return df


def clamp_lot(lot: float) -> float:
    return min(MAX_LOT, max(MIN_LOT, lot))


def compute_qty_for_risk(equity: float, risk_pct: float, stop_dist: float,
                          contract: float = CONTRACT_SIZE_XAU,
                          apply_ceiling: bool = True) -> float:
    """Compute lots so that stop-hit loses risk_pct × equity.

    $_at_risk = qty × contract × stop_dist
    So qty = (risk_pct × equity) / (contract × stop_dist)
    """
    if stop_dist <= 0:
        return MIN_LOT
    dollars_at_risk = risk_pct * equity
    qty = dollars_at_risk / (contract * stop_dist)
    return clamp_lot(qty) if apply_ceiling else max(MIN_LOT, qty)


def per_lot_cost(qty: float) -> float:
    """Real broker cost — scales linearly with lot."""
    return COST_PER_LOT_USD * qty


def scenario_replay(
    trades: pd.DataFrame,
    scenario: str,
    *,
    start_balance: float = START_BALANCE,
    risk_pct: float = RISK_PCT,
    apply_per_lot_cost: bool = True,
    apply_ceiling: bool = True,
    annual_reset: bool = False,
    fixed_risk_usd: float | None = None,
) -> pd.DataFrame:
    """Replay all trades with given sizer + cost + reset logic.

    scenario name is metadata.
    """
    balance = start_balance
    total_withdrawn = 0.0
    current_year = None
    rows = []
    for _, t in trades.iterrows():
        yr = int(t["year"])
        if annual_reset and current_year is not None and yr != current_year:
            # Skim excess above start_balance, keep balance at start_balance
            if balance > start_balance:
                total_withdrawn += (balance - start_balance)
                balance = start_balance
        current_year = yr

        stop_dist = abs(t["entry_price"] - t["stop_price"])

        # Compute qty
        if fixed_risk_usd is not None:
            # Fixed $ risk (no sizer)
            qty = fixed_risk_usd / (CONTRACT_SIZE_XAU * stop_dist) if stop_dist > 0 else MIN_LOT
            qty = clamp_lot(qty) if apply_ceiling else max(MIN_LOT, qty)
        else:
            qty = compute_qty_for_risk(balance, risk_pct, stop_dist,
                                        apply_ceiling=apply_ceiling)

        # Cost model
        if apply_per_lot_cost:
            cost_usd = per_lot_cost(qty)
        else:
            cost_usd = float(t["bt_cost_r"]) * stop_dist  # BT's fixed 0.65 rebuilt to $

        # $ pnl = gross_r × (qty × contract × stop_dist) − cost_usd
        gross_r = float(t["gross_r_bracket"]) + float(t["partial_r"])
        # gross_r already contains partial_r if bracket walk finished
        # We use gross_r_bracket + partial_r separately from BT for clarity
        # Actually gross_r_bracket in DB IS bracket_1r_outcome = final_r + partial. Use as-is.
        gross_r = float(t["gross_r_bracket"])
        pnl_usd = gross_r * qty * CONTRACT_SIZE_XAU * stop_dist - cost_usd
        balance += pnl_usd

        rows.append({
            "trade_id": t["trade_id"],
            "entry_ts": t["entry_timestamp"],
            "year": yr,
            "leg": t["leg"],
            "gross_r": gross_r,
            "stop_dist": stop_dist,
            "qty": qty,
            "cost_usd": cost_usd,
            "pnl_usd": pnl_usd,
            "balance_after": balance,
        })

    # Final skim if annual_reset
    if annual_reset and balance > start_balance:
        total_withdrawn += (balance - start_balance)
        balance = start_balance

    df = pd.DataFrame(rows)
    df.attrs["scenario"] = scenario
    df.attrs["final_balance"] = balance
    df.attrs["total_withdrawn"] = total_withdrawn
    df.attrs["total_take_home"] = balance + total_withdrawn - start_balance
    return df


def headline(df: pd.DataFrame) -> dict:
    n = len(df)
    n_win = int((df["pnl_usd"] > 0).sum())
    wr = 100 * n_win / n if n else 0
    profit = float(df.loc[df["pnl_usd"] > 0, "pnl_usd"].sum())
    loss = float(-df.loc[df["pnl_usd"] <= 0, "pnl_usd"].sum())
    pf = profit / loss if loss > 0 else float("inf")
    years = df["year"].max() - df["year"].min() + 1 if n else 0
    return {
        "scenario": df.attrs.get("scenario"),
        "n": n,
        "wr": wr,
        "pf": pf,
        "sum_pnl": float(df["pnl_usd"].sum()),
        "final_balance": df.attrs.get("final_balance"),
        "total_withdrawn": df.attrs.get("total_withdrawn"),
        "total_take_home": df.attrs.get("total_take_home"),
        "years": years,
        "avg_yr": float(df["pnl_usd"].sum()) / years if years else 0,
        "avg_qty": float(df["qty"].mean()),
        "max_qty": float(df["qty"].max()),
        "avg_cost_usd": float(df["cost_usd"].mean()),
    }


def prow(h: dict) -> str:
    tw = h["total_take_home"] or h["sum_pnl"]
    return (f"{h['scenario']:<28s}  n={h['n']:>6,d}  wr={h['wr']:>5.2f}%  "
            f"pf={h['pf']:>5.2f}  net=${h['sum_pnl']:>+12,.0f}  "
            f"final=${h['final_balance']:>10,.0f}  skimmed=${h['total_withdrawn']:>10,.0f}  "
            f"take_home=${tw:>+11,.0f}  avg/yr=${h['avg_yr']:>+10,.0f}  "
            f"avg_qty={h['avg_qty']:.3f}  max_qty={h['max_qty']:.2f}  "
            f"avg_cost=${h['avg_cost_usd']:.2f}")


def main():
    print(f"[{time.strftime('%H:%M:%S')}] loading trades from run {RUN_ID[:8]}...", flush=True)
    trades = load_trades()
    print(f"  {len(trades):,} trades loaded  "
          f"({trades.entry_timestamp.min()} → {trades.entry_timestamp.max()})", flush=True)

    scenarios = [
        # name, kwargs to scenario_replay
        ("baseline_bt (flat_0.65cost)", dict(apply_per_lot_cost=False, apply_ceiling=False)),
        ("P0_per_lot_cost_only", dict(apply_per_lot_cost=True, apply_ceiling=False)),
        ("P0+P3_perlot+ceiling", dict(apply_per_lot_cost=True, apply_ceiling=True)),
        ("P0+P1_perlot+withdraw", dict(apply_per_lot_cost=True, apply_ceiling=False, annual_reset=True)),
        ("P0+P1+P3_REALISTIC", dict(apply_per_lot_cost=True, apply_ceiling=True, annual_reset=True)),
        ("fixed_$150_risk", dict(apply_per_lot_cost=True, apply_ceiling=True, fixed_risk_usd=FIXED_RISK_USD)),
    ]

    summaries = []
    for name, kwargs in scenarios:
        print(f"\n[{time.strftime('%H:%M:%S')}] {name}", flush=True)
        df = scenario_replay(trades, name, **kwargs)
        df.to_parquet(OUT_DIR / f"{name.replace('+','_').replace(' ','_')}.parquet")
        h = headline(df)
        summaries.append(h)
        print(f"  {prow(h)}", flush=True)

    # Summary CSV
    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUT_DIR / "summary.csv", index=False)
    print(f"\n[{time.strftime('%H:%M:%S')}] === FINAL COMPARISON ===", flush=True)
    for h in summaries:
        print(f"  {prow(h)}", flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] DONE", flush=True)


if __name__ == "__main__":
    main()
