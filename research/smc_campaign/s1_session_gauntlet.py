"""S1-long session-frequency gauntlet.

QUESTION: can we raise S1's trade FREQUENCY (currently ~105/yr, killzone-only)
by opening more session windows — WITHOUT touching the edge params (ote/sl_buf/
tp/need_conf frozen)? Frequency gain is only real if the per-trade edge SURVIVES
the full causal gauntlet in the new window: base PF, +1/2/3-bar delay reprice,
cost stress $0.30-0.80, bootstrap P(net<=0), IS(19-23)/OOS(24-26), 7-8/8 years.

A window that only adds trades by lowering PF below gate = REJECT (frequency
without edge = noise). We keep S1's exact winning params; ONLY the session
filter changes. Model B $5k sizing shown per surviving variant.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")

from research.smc_campaign.framework import MTF, sim_price_bracket, _log
from research.smc_campaign.combined_numbers import headline, print_headline
from research.smc_campaign.sweep_engine import fill_setups
from research.smc_campaign.strategies_fast import universe_s1, _price
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig

CONTRACT = 100.0

# S1 FROZEN winning params (from the 50-100k campaign sweep). DO NOT tune.
S1 = dict(rule="15min", k=4, ote=0.786, sl_buf=0.10, tp_mode="3R",
          sweep_lb=6, need_conf=5, use_idm=0, h4_trend=1)

# Session windows to test, defined on NY hour (ny_hr already on the universe).
# kz = current live window (NY 2-11). Others widen it.
SESSIONS = {
    "kz_base (NY2-11)":   lambda h: (h >= 2) & (h <= 11),
    "all_session":        lambda h: np.ones(len(h), dtype=bool),
    "london_only (NY2-5)":lambda h: (h >= 2) & (h <= 5),
    "ny_only (NY7-12)":   lambda h: (h >= 7) & (h <= 12),
    "london+ny (NY2-12)": lambda h: (h >= 2) & (h <= 12),
}


def s1_setups_for_session(mtf, session_mask):
    """Build S1-long setups with frozen params; ONLY the session filter varies."""
    u = universe_s1(mtf, S1["rule"], S1["k"])
    if len(u) == 0:
        return u
    m = (u["side"] == 1) & (u["depth"] <= S1["sweep_lb"])
    conf = 3 + u["fvg"] + u["ob"]
    m &= conf >= S1["need_conf"]
    if S1["h4_trend"]:
        m &= u["h4up"] == 1
    m &= session_mask(u["ny_hr"].values)
    s = u[m]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    rng = (s["swing_hi"] - s["swing_lo"]).values
    entry = s["swing_hi"].values - S1["ote"] * rng
    ssl = s["swing_lo"].values
    sl, tp, risk = _price(side, entry, ssl, S1["sl_buf"], S1["tp_mode"], np.abs(entry - ssl))
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


def model_b(tr, risk_pct=0.015, base=5000.0):
    tr = tr.sort_values("entry_ts").reset_index(drop=True)
    sz = EquitySizer(EquitySizerConfig(start_balance=base, risk_pct=risk_pct))
    peak = base; maxdd = 0.0; sized = 0
    import datetime as _dt
    for row in tr.itertuples():
        ts = row.entry_ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        lot = sz.size_order(symbol="XAUUSD.ecn", stop_distance=row.risk_units, ts=ts)
        if lot > 0:
            sized += 1
        pnl = row.net_r * (row.risk_units * CONTRACT * lot) if lot > 0 else 0.0
        sz.on_trade_closed(pnl_dollars=pnl, close_ts=ts)
        total = sz.equity() + sz.lifetime_skim()
        peak = max(peak, total); maxdd = min(maxdd, total - peak)
    return dict(total=sz.equity() + sz.lifetime_skim(), banked=sz.lifetime_skim(),
                carry=sz.equity(), maxdd=maxdd, sized=sized, n=len(tr))


def audit_session(mtf, name, session_mask):
    print("\n" + "=" * 100)
    print(f"### SESSION: {name} ###")
    setups = s1_setups_for_session(mtf, session_mask)
    if len(setups) < 30:
        print(f"  only {len(setups)} setups — SKIP")
        return None
    sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
    base = sim_price_bracket(sig, mtf.m5, horizon=288)
    h = headline(base)
    print_headline(f"{name} base", h)

    # delay reprice +1/2/3
    op = mtf.m5["open"].values; n = len(mtf.m5)
    for d in (1, 2, 3):
        s = sig.copy()
        s["fill_index"] = s["fill_index"].astype(int) + d
        s = s[s["fill_index"] < n - 2].reset_index(drop=True)
        s["entry_price"] = op[s["fill_index"].values]
        s["risk_units"] = (s["entry_price"] - s["sl_price"]).abs()
        s = s[s["risk_units"] > 0]
        print_headline(f"{name} delay+{d}", headline(sim_price_bracket(s, mtf.m5)))

    # cost stress
    for c in (0.30, 0.50, 0.80):
        print_headline(f"{name} cost${c}", headline(sim_price_bracket(sig, mtf.m5, cost_usd=c)))

    # bootstrap
    r = base["net_r"].values
    rng = np.random.default_rng(13)
    boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(1500)])
    _log(f"  bootstrap net={r.sum():+.1f}R P(net<=0)={(boots <= 0).mean():.4f}")

    # IS/OOS
    print_headline(f"{name} IS19-23", headline(base[base.year <= 2023]))
    print_headline(f"{name} OOS24-26", headline(base[base.year >= 2024]))

    # year table
    yt = base.groupby("year")["net_r"].agg(["sum", "count"]).round(1)
    print("  year-by-year (net R | trades):")
    for y, row in yt.iterrows():
        print(f"    {int(y)}: {row['sum']:>+8.1f}R  ({int(row['count'])} trades)")

    # Model B $
    mb = model_b(base, 0.015)
    print(f"  Model B $5k @1.5%: total ${mb['total']:,.0f} = banked ${mb['banked']:,.0f} "
          f"+ carry ${mb['carry']:,.0f} ({mb['total']/5000:.1f}x) maxDD ${mb['maxdd']:,.0f} "
          f"sized {mb['sized']}/{mb['n']}")
    return dict(name=name, h=h, mb=mb)


def main():
    mtf = MTF()
    _log("S1 session-frequency gauntlet — frozen params, session filter varies")
    results = []
    for name, mask in SESSIONS.items():
        r = audit_session(mtf, name, mask)
        if r:
            results.append(r)

    print("\n" + "#" * 100)
    print("# VERDICT TABLE (gate: PF>=1.3, MAR>=1.5, 7-8/8 yrs, OOS PF>=80% IS, delay+1 survives)")
    print("#" * 100)
    print(f"{'session':<22} {'n':>5} {'/yr':>5} {'PF':>5} {'MAR':>5} {'netR':>8} {'pos':>5} {'ModelB$':>10}")
    for r in results:
        h = r["h"]; mb = r["mb"]
        print(f"{r['name']:<22} {h['n']:>5} {h['per_yr']:>5.0f} {h['pf']:>5.2f} "
              f"{h['mar']:>5.2f} {h['net']:>+8.1f} {h['pos']:>5} ${mb['total']:>9,.0f}")


if __name__ == "__main__":
    main()
