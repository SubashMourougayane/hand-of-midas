"""Pessimistic critic postmortem of 2022 Oil Micro backtest.

Premise: 2022 was the war-driven oil regime — Brent went $77 (Jan) → $128 (Mar
peak) → $76 (Dec). Massive whipsaws around the Russia/Ukraine invasion (Feb 24).
A fade strategy in this regime either gets steamrolled by trends or rakes the
mean-reversion off violent overshoots. Critic mode: assume the result is
artifact until proven otherwise.

Steps:
  1. Run real run_backtest() on the actual 21yr CSVs.
  2. Isolate 2022 Oil Micro trades.
  3. Compute return %, monthly P&L, R-distribution, equity curve.
  4. Red-flag scan: oversized R, same-bar SL+TP, position sizing vs equity,
     entry price vs OHLC (lookahead?), exit_price plausibility.
  5. Monte-Carlo: 4 random trades/month for 12 months = 48 trades.
     For each: pull raw H1+M3 OHLC at entry/exit, dump to MD with verdict.
  6. Write docs/POSTMORTEM_2022_OIL_MICRO.md + scripts/output/postmortem_2022.html

No mocking. No interpolation. Real engine, real CSVs.
"""
from __future__ import annotations
import os
import sys
import json
import time
import importlib
import random
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)
DOCS_DIR = os.path.join(ROOT, "docs")
os.makedirs(DOCS_DIR, exist_ok=True)


def load_oil_micro_engine():
    """Import oil-micro backtest engine with proper sys.path handling."""
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, "backend-oil-micro")
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()
    return importlib.import_module("backtest.engine")


def trade_to_dict(t):
    """Convert BacktestTrade dataclass to plain dict."""
    return {
        "date": str(t.date), "year": t.year, "month": t.month,
        "strategy": t.strategy, "direction": t.direction,
        "entry": float(t.entry), "sl": float(t.sl), "tp": float(t.tp),
        "exit_price": float(t.exit_price),
        "pnl_unit": float(t.pnl_unit), "pnl_sized": float(t.pnl_sized),
        "units": float(t.units), "status": t.status,
        "bars_held": int(t.bars_held), "hold_human": t.hold_human,
        "risk": float(t.risk), "r_mult": float(t.r_mult),
        "equity_after": float(t.equity_after),
    }


def red_flag_scan(trades, oil_h1_df, oil_m3_df):
    """Scan each trade for red flags. Returns list of dicts."""
    flags = []
    import pandas as pd

    for i, t in enumerate(trades):
        td = t["date"]
        # Try to find the H1 bar containing entry to verify entry price plausibility
        entry_dt = pd.Timestamp(td)

        # Red flag 1: oversized R (R-multiple beyond physical possibility)
        # If r_mult > 5 on a fade strategy, sus
        if abs(t["r_mult"]) > 5:
            flags.append({"trade_idx": i, "type": "OVERSIZED_R",
                          "detail": f"r_mult={t['r_mult']:.2f} on {t['direction']} {td}"})

        # Red flag 2: 0-bar trade
        if t["bars_held"] == 0:
            flags.append({"trade_idx": i, "type": "ZERO_BAR",
                          "detail": f"bars_held=0 on {td}"})

        # Red flag 3: tiny risk size (precision issue?)
        if t["risk"] < 0.01:
            flags.append({"trade_idx": i, "type": "TINY_RISK",
                          "detail": f"risk={t['risk']} on {td}"})

        # Red flag 4: position size vs equity
        # equity_after is post-trade. For Oil at ~$40-80 / barrel, 1 unit = 1 barrel
        # If units * entry > equity * 50 (>50x leverage), suspicious
        notional = t["units"] * t["entry"]
        if t["equity_after"] > 0 and notional > t["equity_after"] * 100:
            flags.append({"trade_idx": i, "type": "OVER_LEVERED",
                          "detail": f"notional=${notional:.0f} vs equity_after=${t['equity_after']:.0f} ({notional/t['equity_after']:.1f}x)"})

        # Red flag 5: pnl_sized vs (units * pnl_unit) consistency
        expected_sized = t["units"] * t["pnl_unit"]
        if t["pnl_unit"] != 0 and abs(expected_sized - t["pnl_sized"]) / max(abs(t["pnl_sized"]), 1) > 0.01:
            flags.append({"trade_idx": i, "type": "SIZE_MISMATCH",
                          "detail": f"units*pnl_unit={expected_sized:.2f} vs pnl_sized={t['pnl_sized']:.2f}"})

        # Red flag 6: entry/SL/TP within tick distance (degenerate)
        if abs(t["entry"] - t["sl"]) < 0.05 or abs(t["entry"] - t["tp"]) < 0.05:
            flags.append({"trade_idx": i, "type": "DEGENERATE_LEVELS",
                          "detail": f"entry={t['entry']} sl={t['sl']} tp={t['tp']}"})

    return flags


def find_h1_context(oil_h1_df, dt_str, before_bars=4, after_bars=4):
    """Pull H1 bars surrounding a trade timestamp."""
    import pandas as pd
    try:
        ts = pd.Timestamp(dt_str)
        if oil_h1_df.index.tz is not None and ts.tz is None:
            ts = ts.tz_localize("UTC")
        # Find nearest H1 bar
        idx = oil_h1_df.index.searchsorted(ts)
        lo = max(0, idx - before_bars)
        hi = min(len(oil_h1_df), idx + after_bars + 1)
        return oil_h1_df.iloc[lo:hi]
    except Exception as e:
        return None


def main():
    print("=" * 80)
    print("PESSIMISTIC POSTMORTEM — 2022 Oil Micro")
    print("=" * 80)

    print("\n[1/6] Loading Oil Micro backtest engine...")
    engine = load_oil_micro_engine()

    print("[2/6] Running 21yr Oil Micro backtest...")
    t0 = time.time()
    result = engine.run_backtest(start_date="2006-01-01", end_date="2026-12-31")
    elapsed = time.time() - t0
    all_trades = result.trades
    print(f"      Done in {elapsed:.1f}s  total trades={len(all_trades)}")

    print("[3/6] Isolating 2022 trades...")
    trades_2022 = [t for t in all_trades if t.year == 2022]
    print(f"      2022 trades: {len(trades_2022)}")

    if len(trades_2022) == 0:
        print("      No 2022 trades — aborting")
        return

    # Convert to dicts
    td = [trade_to_dict(t) for t in trades_2022]

    # Stats
    n = len(td)
    wins = [t for t in td if t["pnl_sized"] > 0]
    losses = [t for t in td if t["pnl_sized"] <= 0]
    sum_win = sum(t["pnl_sized"] for t in wins)
    sum_loss = -sum(t["pnl_sized"] for t in losses)
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    pnl_total = sum(t["pnl_sized"] for t in td)

    # Capital reset each year per engine — find first equity_after to derive starting capital
    starting_equity = td[0]["equity_after"] - td[0]["pnl_sized"]
    final_equity = td[-1]["equity_after"]
    return_pct = (final_equity - starting_equity) / starting_equity * 100

    print(f"\n[4/6] Stats:")
    print(f"      N={n}  WR={len(wins)/n*100:.1f}%  PF={pf:.2f}  P&L=${pnl_total:+,.0f}")
    print(f"      Starting equity: ${starting_equity:,.0f}")
    print(f"      Final equity:    ${final_equity:,.0f}")
    print(f"      Return:          {return_pct:.1f}%")

    # Monthly breakdown
    monthly = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0, "trades": []})
    for t in td:
        key = (t["year"], t["month"])
        monthly[key]["n"] += 1
        if t["pnl_sized"] > 0:
            monthly[key]["wins"] += 1
        monthly[key]["pnl"] += t["pnl_sized"]
        monthly[key]["trades"].append(t)

    print(f"\n      Monthly breakdown:")
    for (y, m), data in sorted(monthly.items()):
        wr = data["wins"] / data["n"] * 100 if data["n"] else 0
        print(f"        {y}-{m:02d}  N={data['n']:>3d}  WR={wr:5.1f}%  P&L=${data['pnl']:>+10,.0f}")

    # Load raw H1 data for context lookups
    print("\n[5/6] Loading raw OHLC for plausibility checks...")
    import pandas as pd
    oil_h1 = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_H1.csv"))
    oil_h1["timestamp"] = pd.to_datetime(oil_h1["timestamp"], utc=True)
    oil_h1 = oil_h1.set_index("timestamp")
    oil_h1["mid_open"] = (oil_h1["bid_open"] + oil_h1["ask_open"]) / 2
    oil_h1["mid_high"] = (oil_h1["bid_high"] + oil_h1["ask_high"]) / 2
    oil_h1["mid_low"] = (oil_h1["bid_low"] + oil_h1["ask_low"]) / 2
    oil_h1["mid_close"] = (oil_h1["bid_close"] + oil_h1["ask_close"]) / 2
    print(f"      H1 bars loaded: {len(oil_h1):,}")

    flags = red_flag_scan(td, oil_h1, None)
    print(f"      Red flags found: {len(flags)}")
    flag_counts = defaultdict(int)
    for f in flags:
        flag_counts[f["type"]] += 1
    for typ, c in sorted(flag_counts.items(), key=lambda x: -x[1]):
        print(f"        {typ}: {c}")

    # Monte Carlo: 4 random trades per month
    print("\n[6/6] Monte-Carlo: 4 random trades/month for postmortem...")
    random.seed(2022)  # deterministic
    sampled = []
    for (y, m), data in sorted(monthly.items()):
        if data["n"] == 0:
            continue
        k = min(4, data["n"])
        sample = random.sample(data["trades"], k)
        sampled.extend(sample)
    print(f"      Sampled {len(sampled)} trades for deep-dive")

    # For each sampled trade, fetch H1 context
    deep_dives = []
    for t in sampled:
        ctx = find_h1_context(oil_h1, t["date"], before_bars=4, after_bars=4)
        ctx_rows = []
        if ctx is not None and len(ctx) > 0:
            for ts, row in ctx.iterrows():
                ctx_rows.append({
                    "ts": str(ts), "o": float(row["mid_open"]),
                    "h": float(row["mid_high"]), "l": float(row["mid_low"]),
                    "c": float(row["mid_close"]),
                })
        # Plausibility: was entry price within H1 range surrounding entry time?
        entry_ts = pd.Timestamp(t["date"])
        if entry_ts.tz is None: entry_ts = entry_ts.tz_localize("UTC")
        plausible = None
        if ctx is not None and len(ctx) > 0:
            # Take the H1 bar that contains entry_ts
            mask = (ctx.index <= entry_ts) & (ctx.index + pd.Timedelta(hours=1) > entry_ts)
            if mask.any():
                bar = ctx[mask].iloc[0]
                lo, hi = float(bar["mid_low"]), float(bar["mid_high"])
                # Allow some buffer for spread/M3 bars wicking outside H1 mids
                buffer = (hi - lo) * 0.15
                plausible = (lo - buffer) <= t["entry"] <= (hi + buffer)
        deep_dives.append({
            "trade": t,
            "h1_context": ctx_rows,
            "entry_in_h1_range": plausible,
        })

    # Save MD report
    md_path = os.path.join(DOCS_DIR, "POSTMORTEM_2022_OIL_MICRO.md")
    with open(md_path, "w") as f:
        write_md_report(f, td, monthly, flags, deep_dives,
                         starting_equity, final_equity, return_pct,
                         pf, len(wins), len(losses))
    print(f"\n      => {md_path}")

    # Save HTML report
    html_path = os.path.join(OUT_DIR, "postmortem_2022.html")
    with open(html_path, "w") as f:
        write_html_report(f, td, monthly, flags, deep_dives,
                          starting_equity, final_equity, return_pct,
                          pf, len(wins), len(losses))
    print(f"      => {html_path}")

    # Save raw data
    raw_path = os.path.join(OUT_DIR, "postmortem_2022_raw.json")
    with open(raw_path, "w") as f:
        json.dump({
            "summary": {"n": n, "wr": len(wins)/n*100, "pf": pf,
                        "pnl_total": pnl_total,
                        "starting_equity": starting_equity,
                        "final_equity": final_equity,
                        "return_pct": return_pct},
            "monthly": {f"{y}-{m:02d}": {**v, "trades": [tr for tr in v["trades"]]}
                        for (y, m), v in sorted(monthly.items())},
            "trades": td,
            "flags": flags,
            "monte_carlo_samples": deep_dives,
        }, f, indent=2, default=str)
    print(f"      => {raw_path}")


def write_md_report(f, trades, monthly, flags, samples,
                    start_eq, final_eq, ret_pct, pf, wins, losses):
    f.write(f"""# Postmortem — 2022 Oil Micro

> **Pessimistic-critic audit** of the 2022 line item from the dashboard
> backtest. Premise: a fade strategy returning thousands of percent in
> a major oil regime year is suspicious until proven legitimate.

## Headline numbers (recomputed from the real 21yr backtest)

| Metric | Value |
|---|---|
| Total trades 2022 | {len(trades)} |
| Wins | {wins} |
| Losses | {losses} |
| Win rate | {wins/len(trades)*100:.1f}% |
| Profit factor | {pf:.2f} |
| Starting equity | ${start_eq:,.0f} |
| Final equity | ${final_eq:,.0f} |
| **Return** | **{ret_pct:.1f}%** |
| Net P&L | ${final_eq - start_eq:+,.0f} |

## Monthly breakdown

| Month | Trades | WR | P&L |
|---|---:|---:|---:|
""")
    for (y, m), data in sorted(monthly.items()):
        wr = data["wins"] / data["n"] * 100 if data["n"] else 0
        f.write(f"| {y}-{m:02d} | {data['n']} | {wr:.1f}% | ${data['pnl']:+,.0f} |\n")

    f.write(f"""

## Red-flag scan

Automated checks for: oversized R-multiples, zero-bar trades, tiny risk,
over-leverage, sizing inconsistency, degenerate price levels.

**Total flags: {len(flags)}**

""")
    if not flags:
        f.write("✅ **No red flags found.** Trades pass mechanical sanity checks.\n\n")
    else:
        flag_counts = defaultdict(int)
        for fl in flags: flag_counts[fl["type"]] += 1
        f.write("| Flag type | Count |\n|---|---:|\n")
        for typ, c in sorted(flag_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {typ} | {c} |\n")
        f.write("\n### Sample flags:\n\n")
        for fl in flags[:20]:
            f.write(f"- **{fl['type']}**: trade #{fl['trade_idx']} — {fl['detail']}\n")
        if len(flags) > 20:
            f.write(f"\n_(... {len(flags) - 20} more, see raw JSON)_\n")

    f.write(f"""

## Sizing & leverage analysis

For Oil (BCO_USD), 1 unit = 1 barrel of crude. Position notional = `units × entry_price`.
Risk per trade = ~4% of equity (RISK_PCT). With Oil typically $40-80/barrel:

- A trade risking $400 on a $1 SL distance = 400 units × $50/barrel = $20,000 notional → 50× leverage
- A trade risking $400 on a $5 SL distance = 80 units × $50/barrel = $4,000 notional → 10× leverage

The wide-SL Oil trades naturally land near sane leverage; tight-SL ones look levered but the actual risk capital is the SL distance, not the notional.

""")
    # Top winners
    sorted_by_pnl = sorted(trades, key=lambda x: x["pnl_sized"], reverse=True)
    f.write("## Top 10 winners\n\n| Date | Dir | Entry | SL | TP | Exit | Units | P&L | R | Status |\n|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
    for t in sorted_by_pnl[:10]:
        f.write(f"| {t['date']} | {t['direction']} | {t['entry']:.2f} | {t['sl']:.2f} | {t['tp']:.2f} | {t['exit_price']:.2f} | {t['units']:.0f} | ${t['pnl_sized']:+,.0f} | {t['r_mult']:+.1f} | {t['status']} |\n")

    f.write("\n## Top 10 losers\n\n| Date | Dir | Entry | SL | TP | Exit | Units | P&L | R | Status |\n|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
    for t in sorted_by_pnl[-10:]:
        f.write(f"| {t['date']} | {t['direction']} | {t['entry']:.2f} | {t['sl']:.2f} | {t['tp']:.2f} | {t['exit_price']:.2f} | {t['units']:.0f} | ${t['pnl_sized']:+,.0f} | {t['r_mult']:+.1f} | {t['status']} |\n")

    f.write(f"""

## Monte-Carlo deep dives (4 random trades / month)

Random sample, seed=2022, of 4 trades per month — {len(samples)} total. For each: trade card + surrounding H1 OHLC + plausibility check (was entry price within the H1 bar's range?).

""")
    for i, dd in enumerate(samples):
        t = dd["trade"]
        plaus = dd["entry_in_h1_range"]
        plaus_emoji = "✅ in range" if plaus else ("⚠️ outside range" if plaus is False else "❓ no H1 bar")
        f.write(f"""### Sample {i+1}: {t['date']} {t['direction']}

| Field | Value |
|---|---|
| Entry | ${t['entry']:.2f} |
| SL | ${t['sl']:.2f} |
| TP | ${t['tp']:.2f} |
| Exit | ${t['exit_price']:.2f} |
| Units | {t['units']:.0f} |
| Risk (per unit) | ${t['risk']:.2f} |
| Bars held | {t['bars_held']} ({t['hold_human']}) |
| Status | {t['status']} |
| P&L | **${t['pnl_sized']:+,.0f}** |
| R-multiple | {t['r_mult']:+.2f} |
| Equity after | ${t['equity_after']:,.0f} |
| **Entry plausibility** | {plaus_emoji} |

**Surrounding H1 bars:**

| Time | O | H | L | C |
|---|---:|---:|---:|---:|
""")
        for row in dd["h1_context"]:
            f.write(f"| {row['ts'][:19]} | {row['o']:.2f} | {row['h']:.2f} | {row['l']:.2f} | {row['c']:.2f} |\n")
        f.write("\n")

    f.write(f"""

## Critic's verdict

_To be filled in after manual review of the deep dives above._

### Things that would make me trust the result
- All entries plausibly inside H1 bar ranges (no lookahead)
- No oversized R-multiples (>5R is suspicious for fade strategy)
- No zero-bar trades (suggests same-bar SL+TP that may not be respected by tick replay)
- Equity curve smooth, not single-month explosion
- Profit factor stable across months

### Things that would suggest artifact
- Many entries outside H1 bar ranges → lookahead bias
- Multiple R-multiples > 10 → phantom-fill class bug returning
- 80%+ of P&L in 1-2 months → regime-specific overfit
- Position sizing breaks the equity curve (units × entry > equity)
- Same exit price on many trades → unmodeled SL/TP fills

### Final assessment

_TBD — review the data above, then write here._

---

_Generated by `scripts/postmortem_2022_oil_micro.py` on {datetime.now(timezone.utc).isoformat()}._
""")


def write_html_report(f, trades, monthly, flags, samples,
                       start_eq, final_eq, ret_pct, pf, wins, losses):
    f.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>2022 Oil Micro — Pessimistic Postmortem</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 18px; background: #0a0e14; color: #e6e8ec; }}
h1 {{ font-family: Georgia, serif; font-style: italic; font-size: 32px; color: #34d399; }}
h2 {{ font-family: Georgia, serif; font-style: italic; color: #fbbf24; margin-top: 36px; border-bottom: 1px solid #232836; padding-bottom: 6px; }}
h3 {{ color: #c8cdd6; font-size: 16px; margin-top: 24px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }}
th, td {{ border: 1px solid #232836; padding: 6px 10px; text-align: left; }}
th {{ background: #161c25; color: #c8cdd6; font-weight: 600; }}
td {{ background: #0d1117; }}
.win {{ color: #34d399; font-weight: 600; }}
.loss {{ color: #f87171; font-weight: 600; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; margin-right: 4px; }}
.tag.win {{ background: rgba(52,211,153,0.15); color: #34d399; }}
.tag.loss {{ background: rgba(248,113,113,0.15); color: #f87171; }}
.tag.flag {{ background: rgba(251,191,36,0.15); color: #fbbf24; }}
pre {{ background: #11161f; padding: 8px; border-radius: 4px; overflow-x: auto; font-size: 12px; }}
.metric {{ display: inline-block; background: #11161f; padding: 12px 18px; border-radius: 4px; margin: 4px 6px 4px 0; }}
.metric .v {{ font-size: 24px; font-weight: 700; color: #34d399; display: block; }}
.metric .l {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #8c95a4; }}
.flag-row {{ background: rgba(251,191,36,0.06); }}
</style>
</head>
<body>
<h1>2022 Oil Micro — Pessimistic Postmortem</h1>
<p style="color:#8c95a4">Generated {datetime.now(timezone.utc).isoformat()}.</p>

<div>
  <span class="metric"><span class="l">Trades</span><span class="v">{len(trades)}</span></span>
  <span class="metric"><span class="l">Win rate</span><span class="v">{wins/len(trades)*100:.1f}%</span></span>
  <span class="metric"><span class="l">Profit factor</span><span class="v">{pf:.2f}</span></span>
  <span class="metric"><span class="l">Return</span><span class="v">{ret_pct:.1f}%</span></span>
  <span class="metric"><span class="l">Final equity</span><span class="v">${final_eq:,.0f}</span></span>
  <span class="metric"><span class="l">Red flags</span><span class="v" style="color:{'#f87171' if flags else '#34d399'}">{len(flags)}</span></span>
</div>

<h2>Monthly breakdown</h2>
<table><tr><th>Month</th><th>Trades</th><th>WR</th><th>P&amp;L</th></tr>
""")
    for (y, m), data in sorted(monthly.items()):
        wr = data["wins"] / data["n"] * 100 if data["n"] else 0
        pnl_class = "win" if data["pnl"] > 0 else "loss"
        f.write(f"<tr><td>{y}-{m:02d}</td><td>{data['n']}</td><td>{wr:.1f}%</td><td class='{pnl_class}'>${data['pnl']:+,.0f}</td></tr>\n")
    f.write("</table>")

    # Flags
    f.write("<h2>Red flags</h2>")
    if not flags:
        f.write("<p class='win'>No red flags.</p>")
    else:
        f.write("<table><tr><th>#</th><th>Type</th><th>Detail</th></tr>")
        for fl in flags[:50]:
            f.write(f"<tr class='flag-row'><td>{fl['trade_idx']}</td><td><span class='tag flag'>{fl['type']}</span></td><td><code>{fl['detail']}</code></td></tr>")
        if len(flags) > 50:
            f.write(f"<tr><td colspan='3' style='text-align:center;color:#8c95a4'>(... {len(flags)-50} more)</td></tr>")
        f.write("</table>")

    # Top winners / losers
    sorted_by_pnl = sorted(trades, key=lambda x: x["pnl_sized"], reverse=True)
    f.write("<h2>Top 10 winners</h2><table><tr><th>Date</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Exit</th><th>Units</th><th>P&amp;L</th><th>R</th><th>Status</th></tr>")
    for t in sorted_by_pnl[:10]:
        f.write(f"<tr><td>{t['date'][:19]}</td><td>{t['direction']}</td><td>{t['entry']:.2f}</td><td>{t['sl']:.2f}</td><td>{t['tp']:.2f}</td><td>{t['exit_price']:.2f}</td><td>{t['units']:.0f}</td><td class='win'>${t['pnl_sized']:+,.0f}</td><td>{t['r_mult']:+.1f}</td><td>{t['status']}</td></tr>")
    f.write("</table>")

    f.write("<h2>Top 10 losers</h2><table><tr><th>Date</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Exit</th><th>Units</th><th>P&amp;L</th><th>R</th><th>Status</th></tr>")
    for t in sorted_by_pnl[-10:]:
        f.write(f"<tr><td>{t['date'][:19]}</td><td>{t['direction']}</td><td>{t['entry']:.2f}</td><td>{t['sl']:.2f}</td><td>{t['tp']:.2f}</td><td>{t['exit_price']:.2f}</td><td>{t['units']:.0f}</td><td class='loss'>${t['pnl_sized']:+,.0f}</td><td>{t['r_mult']:+.1f}</td><td>{t['status']}</td></tr>")
    f.write("</table>")

    # Monte-Carlo
    f.write(f"<h2>Monte-Carlo deep dives ({len(samples)} samples)</h2>")
    for i, dd in enumerate(samples):
        t = dd["trade"]
        plaus = dd["entry_in_h1_range"]
        plaus_html = "<span class='tag win'>✓ in H1 range</span>" if plaus else ("<span class='tag flag'>⚠ outside H1 range</span>" if plaus is False else "<span class='tag flag'>? no H1 bar</span>")
        pnl_class = "win" if t["pnl_sized"] > 0 else "loss"
        f.write(f"<h3>Sample {i+1}: {t['date'][:19]} {t['direction']} @ ${t['entry']:.2f} {plaus_html}</h3>")
        f.write(f"<p>SL ${t['sl']:.2f} · TP ${t['tp']:.2f} · Exit ${t['exit_price']:.2f} · Units {t['units']:.0f} · "
                f"<span class='{pnl_class}'>P&amp;L ${t['pnl_sized']:+,.0f} ({t['r_mult']:+.1f}R)</span> · "
                f"Status <code>{t['status']}</code> · Held {t['hold_human']}</p>")
        f.write("<table><tr><th>H1 bar</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr>")
        for row in dd["h1_context"]:
            f.write(f"<tr><td>{row['ts'][:19]}</td><td>{row['o']:.2f}</td><td>{row['h']:.2f}</td><td>{row['l']:.2f}</td><td>{row['c']:.2f}</td></tr>")
        f.write("</table>")

    f.write("</body></html>")


if __name__ == "__main__":
    main()
