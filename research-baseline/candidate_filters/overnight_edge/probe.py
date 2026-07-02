"""OVERNIGHT-CARRY as a tradeable signal — probe.

KNOWN FACT (from baseline): trades held across a UTC calendar day ("overnight")
have PF ~4.1 (5.2 in some cuts), intraday PF 0.74. BUT 'overnight' is an
EXIT-TIME label — you only know a trade carried once it has NOT hit SL/TP by
day-end. It is NOT knowable at entry_ts. Trading it directly = look-ahead.

RESEARCH QUESTION: is there an AT-ENTRY proxy (causal, knowable at entry_ts)
that predicts which trades will carry overnight AND win — thereby capturing the
overnight edge without the look-ahead label?

Candidate proxies, all knowable at entry_ts:
  P1  entry UTC hour buckets (late-session entries carry more often)
  P2  entry NY hour (ny_hr from raw_features — session-relative)
  P3  day-of-week
  P4  TP distance in D1-ATR units (far TP => needs overnight to reach)
  P5  fib_diff / D1_ATR (impulse strength — already a known signal)
  P6  entry near session open (Asia/London/NY open windows)
  P7  COMBINED: late-session entry AND large TP (both push overnight carry)

For each: split trades, compute PF/WR/net-R/pos-years filtered vs baseline.

Bible: D1_ATR attached via attach_htf_feature_causal (last D1 bar with
close_ts <= entry_ts). Entry hour/dow are trivially causal (timestamp is the
entry itself). NO exit-time info used in any rule.

Zero edits to strategy/BT/live. Post-hoc on bt_trades + raw M5.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research-baseline/candidate_filters")

import numpy as np
import pandas as pd
import _causal_lib as L

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)


def build():
    t = L.load_trades()
    m5 = L.load_m5()
    # D1 ATR (14) — causal rolling on closed D1 bars
    d1 = L.resample_causal(m5, "1D")
    d1["tr"] = np.maximum(
        d1.high - d1.low,
        np.maximum((d1.high - d1.close.shift(1)).abs(),
                   (d1.low - d1.close.shift(1)).abs()))
    d1 = L.rolling_feature_causal(d1, "tr", 14, "mean", "d1_atr")
    t = L.attach_htf_feature_causal(t, d1, "d1_atr", "d1_atr")

    t["utc_hr"] = t.entry_timestamp.dt.hour
    t["dow"] = t.entry_timestamp.dt.dayofweek  # 0=Mon
    t["tp_dist"] = (t.take_profit_price - t.entry_price).abs()
    t["tp_atr"] = t.tp_dist / t.d1_atr
    t["fib_over_atr"] = t.fib_diff / t.d1_atr
    return t


def report(t, mask, name, rule):
    sub = t[mask]
    n = len(sub)
    base_pf = L.headline(t)["pf"]
    h = L.headline(sub)
    py_f = L.yearly_positive(sub)
    py_b = L.yearly_positive(t)
    # net-R delta if we KEEP only the filtered set vs dropping the rest.
    # A useful loss-cut filter drops trades: delta = -(net_r of dropped losers)
    #   minus net_r of dropped winners. Here mask = KEEP set, so dropped = ~mask.
    dropped = t[~mask]
    dropped_loser_r = dropped.loc[dropped.net_r <= 0, "net_r"].sum()  # negative
    dropped_winner_r = dropped.loc[dropped.net_r > 0, "net_r"].sum()  # positive
    delta_r = (-dropped_loser_r) - dropped_winner_r  # R saved net if we drop ~mask
    on_rate = sub.overnight.mean() if n else float("nan")
    print(f"\n### {name}")
    print(f"    rule: {rule}")
    print(f"    n={n} ({100*n/len(t):.1f}% of {len(t)})  on_rate={on_rate:.2f}")
    print(f"    PF {base_pf:.3f} -> {h['pf']:.3f}   WR {100*t.win.mean():.1f} -> {100*sub.win.mean():.1f}")
    print(f"    kept sumR={h['sum_r']}  pos-years {py_f[0]}/{py_f[1]} (base {py_b[0]}/{py_b[1]})")
    print(f"    delta_R (drop ~mask) = {delta_r:.1f}  [saved losers {-dropped_loser_r:.1f} - lost winners {dropped_winner_r:.1f}]")
    return dict(name=name, rule=rule, n=n, base_pf=base_pf, pf=h["pf"],
                delta_r=round(delta_r, 1), pos=f"{py_f[0]}/{py_f[1]}",
                on_rate=round(float(on_rate), 3), kept_sumr=h["sum_r"])


def main():
    t = build()
    print("BASELINE", L.headline(t, "ALL"), "pos-years", L.yearly_positive(t))
    print("OVERNIGHT (exit-label, NOT tradeable)", L.headline(t[t.overnight == 1]))
    print("INTRADAY  (exit-label)", L.headline(t[t.overnight == 0]))

    # ---- P1: entry UTC hour buckets -----------------------------------
    print("\n" + "=" * 70 + "\nP1  ENTRY UTC-HOUR BUCKETS\n" + "=" * 70)
    print("per-hour on_rate / PF / net_r:")
    for h in range(24):
        s = t[t.utc_hr == h]
        if len(s) < 50:
            continue
        print(f"  hr {h:2d} n={len(s):5d} on={s.overnight.mean():.2f} "
              f"PF={L.headline(s)['pf']:.2f} sumR={s.net_r.sum():7.1f} wr={100*s.win.mean():.1f}")
    report(t, t.utc_hr.between(15, 23), "P1a late-session (hr15-23)",
           "entry_utc_hour in [15,23]  (high overnight carry)")
    report(t, t.utc_hr.between(11, 14), "P1b mid-session (hr11-14)",
           "entry_utc_hour in [11,14]  (best raw PF)")

    # ---- P2: NY hour --------------------------------------------------
    print("\n" + "=" * 70 + "\nP2  ENTRY NY-HOUR (ny_hr from raw_features)\n" + "=" * 70)
    for h in range(24):
        s = t[t.ny_hr == h]
        if len(s) < 50:
            continue
        print(f"  ny {h:2d} n={len(s):5d} on={s.overnight.mean():.2f} "
              f"PF={L.headline(s)['pf']:.2f} sumR={s.net_r.sum():7.1f}")

    # ---- P3: day of week ----------------------------------------------
    print("\n" + "=" * 70 + "\nP3  DAY-OF-WEEK\n" + "=" * 70)
    for d in range(7):
        s = t[t.dow == d]
        if len(s) < 50:
            continue
        print(f"  dow {d} n={len(s):5d} on={s.overnight.mean():.2f} "
              f"PF={L.headline(s)['pf']:.2f} sumR={s.net_r.sum():7.1f}")

    # ---- P4: TP distance in ATR --------------------------------------
    print("\n" + "=" * 70 + "\nP4  TP-DISTANCE / D1_ATR\n" + "=" * 70)
    d = t.dropna(subset=["tp_atr"])
    print(d.groupby(pd.qcut(d.tp_atr, 5, duplicates="drop"))
          .apply(lambda s: pd.Series({"n": len(s), "on": s.overnight.mean(),
                                       "PF": L.headline(s)["pf"], "sumR": s.net_r.sum(),
                                       "wr": 100 * s.win.mean()}), include_groups=False))

    # ---- P5: fib_diff / ATR (impulse) --------------------------------
    print("\n" + "=" * 70 + "\nP5  FIB_DIFF / D1_ATR (impulse strength)\n" + "=" * 70)
    d = t.dropna(subset=["fib_over_atr"])
    print(d.groupby(pd.qcut(d.fib_over_atr, 5, duplicates="drop"))
          .apply(lambda s: pd.Series({"n": len(s), "on": s.overnight.mean(),
                                       "PF": L.headline(s)["pf"], "sumR": s.net_r.sum(),
                                       "wr": 100 * s.win.mean()}), include_groups=False))

    # ---- CRITICAL TEST: does the entry-time proxy INHERIT the overnight PF? --
    # If overnight edge is tradeable via late-entry, then late-entry trades that
    # DO carry overnight should keep PF~4. If it's just exit-time survivorship,
    # the proxy captures carry but NOT the elevated PF.
    print("\n" + "=" * 70 + "\nDIAGNOSTIC: does late-entry INHERIT overnight PF?\n" + "=" * 70)
    late = t[t.utc_hr.between(15, 23)]
    print("  late-entry ALL     ", L.headline(late))
    print("  late-entry & carried", L.headline(late[late.overnight == 1]),
          "<- but 'carried' is EXIT-label, not tradeable")
    print("  late-entry intraday ", L.headline(late[late.overnight == 0]))
    print("  => the PF of late-entry OVERALL is what you actually get at entry.")

    # ---- P7 combined --------------------------------------------------
    print("\n" + "=" * 70 + "\nP7  COMBINED: mid/late entry x large TP\n" + "=" * 70)
    res = []
    res.append(report(t, (t.utc_hr.between(11, 18)) & (t.tp_atr > 1.0),
                      "P7a hr11-18 & tp_atr>1", "utc_hr in[11,18] & tp/D1ATR>1.0"))
    res.append(report(t, (t.utc_hr.between(11, 14)),
                      "P7b hr11-14 only", "utc_hr in[11,14]"))
    res.append(report(t, (t.utc_hr.between(12, 13)),
                      "P7c hr12-13 peak", "utc_hr in[12,13]"))
    res.append(report(t, (t.utc_hr.between(11, 18)),
                      "P7d hr11-18 broad", "utc_hr in[11,18]"))
    return t


if __name__ == "__main__":
    main()
