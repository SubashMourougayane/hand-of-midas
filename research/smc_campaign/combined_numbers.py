"""EVERY number: S1-long (new SMC winner) + Fib V2 A+D intraday (LIVE strategy).

Split (each strategy alone) AND merged (both on ONE shared account, chronological).
No fake fills: S1 uses realistic 0.05-ATR adverse slip on the OTE limit; A+D trades
are the certified causal parity parquets (net_r already net of cost). No look-ahead:
S1 built from the causal primitives (arm_ts = fully-confirmed setup). Single account —
merge is chronological on one equity curve (NEVER sum separate snapshots).

Outputs, per strategy AND merged:
  - headline (n, /yr, PF, WR, avg RR, net R, MAR, maxDD-R, pos years)
  - year-by-year net R + trade count
  - Model B $5,000 @ 1.5% monthly-skim $ PnL (production sizer) + per-year skim
  - flat-R compounding $ curve at 1/2/3%

Live strategy = Fib V2 A+D intraday (M15, lb3, PTP) — the two legs share the account.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")

from research.smc_campaign.framework import MTF, sim_price_bracket, _log
from research.smc_campaign.sweep_engine import fill_setups
from research.smc_campaign import strategies_fast as SF
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig
import logging
logging.disable(logging.CRITICAL)

AD_A = "/Users/subash/SUBASH/GoldDigger/research/fib_retrace/intraday_dedup/intraday_a_trades.parquet"
AD_D = "/Users/subash/SUBASH/GoldDigger/research/fib_retrace/intraday_dedup/intraday_d_trades.parquet"
CONTRACT = 100.0  # XAU: 1 lot = 100 oz


# ---------------- trade generation ----------------
def gen_s1_long(mtf):
    """Certified S1-long winner (realistic 0.05-ATR slip). Returns trades df with
    entry_ts, net_r, risk_units, year, side."""
    setups = SF.price_s1(mtf, rule="15min", k=4, ote=0.786, sl_buf=0.10, tp_mode="3R",
                         sweep_lb=6, need_conf=5, use_idm=0, h4_trend=1, session="kz",
                         sides=(1,))
    sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
    tr = sim_price_bracket(sig, mtf.m5, horizon=288)
    tr = tr.rename(columns={})[["entry_ts", "side", "net_r", "risk_units", "rr", "year"]].copy()
    tr["entry_ts"] = pd.to_datetime(tr["entry_ts"])
    tr["strategy"] = "S1_long"
    return tr.sort_values("entry_ts").reset_index(drop=True)


def load_ad():
    """Fib V2 A+D intraday LIVE trades (causal parity parquets). net_r net of cost."""
    frames = []
    for path, leg in [(AD_A, "AD_A_long"), (AD_D, "AD_D_short")]:
        df = pd.read_parquet(path)
        df["entry_ts"] = pd.to_datetime(df["entry_ts"])
        df["strategy"] = leg
        frames.append(df[["entry_ts", "side", "net_r", "risk_units", "year", "strategy"]])
    ad = pd.concat(frames, ignore_index=True).sort_values("entry_ts").reset_index(drop=True)
    return ad


# ---------------- stats ----------------
def headline(tr):
    if len(tr) == 0:
        return {}
    r = tr["net_r"].astype(float)
    n = len(r); net = float(r.sum()); wr = float((r > 0).mean())
    gw = float(r[r > 0].sum()); gl = float(-r[r < 0].sum())
    pf = gw / gl if gl > 0 else float("inf")
    eq = r.cumsum().values; peak = np.maximum.accumulate(eq); dd = float((eq - peak).min())
    ts = pd.to_datetime(tr["entry_ts"]); yrs = max(0.01, (ts.max() - ts.min()).total_seconds() / (365.25 * 86400))
    y = tr.groupby(tr["entry_ts"].dt.year)["net_r"].sum()
    pos = int((y > 0).sum()); tot = int(len(y))
    return dict(n=n, per_yr=n / yrs, net=net, wr=wr, pf=pf, dd=dd,
                yr_r=net / yrs, mar=(net / yrs) / abs(dd) if dd else 0,
                pos=f"{pos}/{tot}", avg_rr=float(tr["rr"].mean()) if "rr" in tr else float("nan"),
                span=f"{ts.min().date()}..{ts.max().date()}")


def print_headline(label, h):
    if not h:
        print(f"  {label:<22} EMPTY"); return
    rr = f"{h['avg_rr']:.2f}" if not np.isnan(h.get("avg_rr", np.nan)) else "  - "
    print(f"  {label:<22} n={h['n']:>5} /yr={h['per_yr']:>5.0f} PF={h['pf']:>5.2f} "
          f"WR={h['wr']*100:>4.1f}% RR={rr} net={h['net']:>+8.1f}R /yr={h['yr_r']:>+6.1f} "
          f"maxDD={h['dd']:>+7.1f}R MAR={h['mar']:>+5.2f} pos={h['pos']} [{h['span']}]")


def year_table(tr, label):
    print(f"\n  --- {label}: year-by-year (net R | trades) ---")
    g = tr.groupby(tr["entry_ts"].dt.year)["net_r"].agg(["sum", "count"]).round(1)
    for y, row in g.iterrows():
        print(f"    {int(y)}: {row['sum']:>+8.1f}R  ({int(row['count'])} trades)")


def model_b(tr, risk_pct=0.015, base=5000.0):
    """Run trades through the production EquitySizer (Model B monthly skim). Uses
    risk_units as stop_distance, XAU contract. Returns banked, carry, per-year skim,
    per-year $ pnl, avg lot, maxDD$."""
    tr = tr.sort_values("entry_ts").reset_index(drop=True)
    sz = EquitySizer(EquitySizerConfig(start_balance=base, risk_pct=risk_pct))
    per = []
    peak = base; maxdd = 0.0
    for row in tr.itertuples():
        ts = row.entry_ts.to_pydatetime()
        if ts.tzinfo is None:
            import datetime as _dt
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        lot = sz.size_order(symbol="XAUUSD.ecn", stop_distance=row.risk_units, ts=ts)
        pnl = row.net_r * (row.risk_units * CONTRACT * lot) if lot > 0 else 0.0
        sz.on_trade_closed(pnl_dollars=pnl, close_ts=ts)
        total = sz.equity() + sz.lifetime_skim()
        peak = max(peak, total); maxdd = min(maxdd, total - peak)
        per.append({"year": row.entry_ts.year, "pnl": pnl, "lot": lot})
    pf = pd.DataFrame(per)
    skim = pd.DataFrame(sz.state.skim_history)
    banked = sz.lifetime_skim(); carry = sz.equity()
    return dict(banked=banked, carry=carry, total=banked + carry, maxdd=maxdd,
                per_year=pf, skim=skim, sized=(pf.lot > 0).sum(), n=len(pf))


def flat_curve(tr, risk_pct, base=5000.0):
    eq = base; peak = base; dd = 0.0
    for r in tr.sort_values("entry_ts").itertuples():
        eq += eq * risk_pct * r.net_r; peak = max(peak, eq); dd = min(dd, eq - peak)
    return eq, 100 * dd / peak if peak else 0.0


def report(tr, label, do_year=True):
    print(f"\n{'='*100}\n### {label} ###")
    h = headline(tr); print_headline(label, h)
    if do_year:
        year_table(tr, label)
    print(f"\n  --- {label}: flat-R compound from $5,000 ---")
    for rp in (0.01, 0.02, 0.03):
        f, dd = flat_curve(tr, rp)
        print(f"    {rp*100:.0f}% risk: ${f:>14,.0f}  maxDD {dd:>6.1f}%  ({f/5000:.1f}x)")
    mb = model_b(tr, 0.015)
    print(f"\n  --- {label}: Model B $5,000 @ 1.5% monthly skim (production sizer) ---")
    print(f"    total ${mb['total']:,.0f} = banked ${mb['banked']:,.0f} + carry ${mb['carry']:,.0f}  "
          f"({mb['total']/5000:.1f}x)  maxDD ${mb['maxdd']:,.0f}  sized {mb['sized']}/{mb['n']}")
    if len(mb["skim"]):
        sk = mb["skim"].copy(); sk["yr"] = sk["month_closed"].str[:4]
        ys = sk.groupby("yr")["skim_amount"].sum()
        py = mb["per_year"].groupby("year")["pnl"].sum()
        print(f"    per-year: skim$ | gross$ | avg lot")
        for yr in sorted(mb["per_year"]["year"].unique()):
            s = ys.get(str(yr), 0.0)
            g = py.get(yr, 0.0)
            al = mb["per_year"][mb["per_year"].year == yr]["lot"].mean()
            print(f"      {yr}: skim ${s:>9,.0f} | gross ${g:>+9,.0f} | lot {al:.2f}")
    return h, mb


def main():
    mtf = MTF()
    _log("generating S1-long trades …")
    s1 = gen_s1_long(mtf)
    _log(f"S1-long: {len(s1)} trades")
    ad = load_ad()
    a = ad[ad.strategy == "AD_A_long"]; d = ad[ad.strategy == "AD_D_short"]
    _log(f"A+D: {len(ad)} trades (A={len(a)} D={len(d)})")

    print("\n" + "#" * 100)
    print("# EVERY NUMBER — S1-long (new SMC winner) + Fib V2 A+D intraday (LIVE)")
    print("# Realistic fills (S1 0.05ATR slip; A+D causal parity), no look-ahead, single account.")
    print("#" * 100)

    # ---- SPLIT: each strategy standalone (full history) ----
    print("\n" + "="*100 + "\n>>> PART 1 — EACH STRATEGY STANDALONE (full history) <<<")
    report(a, "A+D leg A (long, full)")
    report(d, "A+D leg D (short, full)")
    report(ad, "A+D COMBINED (full)")
    report(s1, "S1-long (full 2019-26)")

    # ---- MERGED: common period, ONE account ----
    start = max(pd.Timestamp("2019-10-01"), s1.entry_ts.min())
    print("\n" + "="*100 + f"\n>>> PART 2 — MERGED on ONE account, common period from {start.date()} <<<")
    adc = ad[ad.entry_ts >= start]
    s1c = s1[s1.entry_ts >= start]
    report(adc, "A+D (common period)")
    report(s1c, "S1-long (common period)")
    merged = pd.concat([adc, s1c], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)
    report(merged, "MERGED A+D + S1 (one account)")

    # ---- per-strategy contribution within merged ----
    print("\n" + "="*100 + "\n>>> PART 3 — contribution split within the MERGED account (common period) <<<")
    for name in ["AD_A_long", "AD_D_short", "S1_long"]:
        sub = merged[merged.strategy == name]
        if len(sub):
            print_headline(name, headline(sub))
    print(f"\n  merged net R = {merged.net_r.sum():+.1f}  "
          f"(A={merged[merged.strategy=='AD_A_long'].net_r.sum():+.1f} "
          f"D={merged[merged.strategy=='AD_D_short'].net_r.sum():+.1f} "
          f"S1={merged[merged.strategy=='S1_long'].net_r.sum():+.1f})")


if __name__ == "__main__":
    main()
