"""Model B sizing on BTC H4 VWAP-mom-L — faithful port of the gold sizer.

Gold Model B (bt_engine/runner/equity_sizer.py):
  - risk_dollar = current_equity * risk_pct  (sized per trade, realized-only)
  - end-of-MONTH asymmetric skim: equity>base → skim profit to base ; equity<=base → keep
User addition: end-of-YEAR reset to base ($1,000) regardless.

Runs 3 models on the SAME trade sequence (net_r per trade, chronological):
  1. Model B monthly-skim ONLY (gold-identical, no annual reset)
  2. Model B monthly-skim + ANNUAL reset to $1,000 (user's ask)
  3. flat compounding (reference)
Base $1,000, risk 3%. Shows skim ledger + all PnL + survival.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.btc_sweep.sweep_all_families import frame, simulate, gen_vwap_mom

BASE = 1000.0
RISK = 0.03


def load():
    b = frame("4h")
    tr = simulate(gen_vwap_mom(b, side=1, sl=1.0), b, tp_mult=3.0, horizon=180).reset_index(drop=True)
    tr["ts"] = pd.to_datetime(tr["entry_ts"], utc=True)
    tr = tr.sort_values("ts").reset_index(drop=True)
    tr["ym"] = tr["ts"].dt.strftime("%Y-%m")
    tr["yr"] = tr["ts"].dt.year
    return tr


def run_model_b(tr, *, annual_reset: bool):
    """Realized-only Model B. Returns (skim_total, ledger_df, equity_path, min_eq, wiped)."""
    eq = BASE
    cur_month = tr["ym"].iloc[0]
    cur_year = int(tr["yr"].iloc[0])
    skim_total = 0.0
    reset_total = 0.0
    ledger = []
    path = []
    wiped = False
    for _, t in tr.iterrows():
        # month roll BEFORE sizing this trade
        if t["ym"] != cur_month:
            if eq > BASE:
                s = eq - BASE; skim_total += s; eq = BASE
                ledger.append({"period": cur_month, "type": "month_skim", "amount": s, "carry": eq})
            else:
                ledger.append({"period": cur_month, "type": "month_keep", "amount": 0.0, "carry": eq})
            cur_month = t["ym"]
        # year roll (user addition): reset to BASE at year boundary
        if annual_reset and int(t["yr"]) != cur_year:
            if eq != BASE:
                reset_total += (eq - BASE)  # can be + (extra skim) or - (topped back up)
                ledger.append({"period": str(cur_year), "type": "year_reset", "amount": eq - BASE, "reset_to": BASE})
            eq = BASE
            cur_year = int(t["yr"])
        if eq <= 0:
            wiped = True; break
        # size on current equity, realized-only
        risk_dollar = eq * RISK
        eq += risk_dollar * t["net_r"]
        path.append(eq)
    # final period skim
    if eq > BASE:
        skim_total += eq - BASE
    path = np.array(path)
    return skim_total, reset_total, pd.DataFrame(ledger), path, (path.min() if len(path) else BASE), wiped


def flat_compound(tr):
    eq = BASE; path = []
    for v in tr["net_r"].values:
        eq *= (1 + RISK * v); path.append(eq)
    return np.array(path)


def maxdd(path, base=BASE):
    pk = np.maximum.accumulate(np.concatenate([[base], path]))
    return ((pk[1:] - path) / pk[1:]).max()


def run():
    tr = load()
    print("█"*74)
    print("  H4 VWAP-MOM-L · MODEL B SIZING · base $1,000 · 3% risk · realized-only")
    print(f"  {len(tr)} trades  {tr['ts'].min().date()} → {tr['ts'].max().date()}")
    print("█"*74)

    # ── Model 1: monthly skim only (gold-identical) ──
    sk1, _, led1, p1, min1, w1 = run_model_b(tr, annual_reset=False)
    print("\n═══ MODEL 1 · MONTHLY SKIM ONLY (gold-identical Model B) ═══")
    print(f"  total skimmed (pocketed): ${sk1:,.0f}")
    print(f"  final account equity    : ${p1[-1]:,.0f}")
    print(f"  TOTAL PROFIT (skim+final-base): ${sk1 + p1[-1] - BASE:,.0f}")
    print(f"  min equity: ${min1:,.0f}   wiped: {w1}   account maxDD: {maxdd(p1):.1%}")
    # per-year skim
    led1["yr"] = led1["period"].str[:4]
    yr_sk = led1[led1["type"] == "month_skim"].groupby("yr")["amount"].sum()
    print("  skim by year:", {k: round(v) for k, v in yr_sk.items()})

    # ── Model 2: monthly skim + annual reset (user's ask) ──
    sk2, rst2, led2, p2, min2, w2 = run_model_b(tr, annual_reset=True)
    print("\n═══ MODEL 2 · MONTHLY SKIM + ANNUAL RESET to $1,000 (your ask) ═══")
    print(f"  total monthly skim      : ${sk2:,.0f}")
    print(f"  total annual-reset flows: ${rst2:,.0f}  (+ = extra pocketed at yr-end, - = topped back to base)")
    print(f"  TOTAL POCKETED          : ${sk2 + rst2:,.0f}")
    print(f"  min equity: ${min2:,.0f}   wiped: {w2}   account maxDD: {maxdd(p2):.1%}")
    # monthly skim detail
    ms = led2[led2["type"] == "month_skim"]
    print(f"  months skimmed: {len(ms)} of {tr['ym'].nunique()}  avg skim ${ms['amount'].mean():,.0f}  best month +${ms['amount'].max():,.0f}")
    yr2 = led2[led2["type"] == "year_reset"][["period", "amount"]]
    print("  year-end equity (before reset to $1k):")
    for _, row in yr2.iterrows():
        print(f"    end {row['period']}: ${BASE + row['amount']:,.0f}  ({'skim +$%.0f' % row['amount'] if row['amount']>0 else 'top-up $%.0f' % row['amount']})")

    # ── Model 3: flat compound reference ──
    p3 = flat_compound(tr)
    print("\n═══ MODEL 3 · FLAT COMPOUND (no skim, reference) ═══")
    print(f"  final equity: ${p3[-1]:,.0f}  ({p3[-1]/BASE-1:+.0%})  maxDD {maxdd(p3):.1%}")

    print("\n═══ HEADLINE COMPARISON (base $1k, 3% risk) ═══")
    print(f"  Model 1 monthly-skim     → pocketed ${sk1:,.0f} + acct ${p1[-1]:,.0f}")
    print(f"  Model 2 skim+annual-reset→ pocketed ${sk2+rst2:,.0f}  (account always resets to $1k)")
    print(f"  Model 3 flat compound    → ${p3[-1]:,.0f}")
    return tr, led2


if __name__ == "__main__":
    run()
