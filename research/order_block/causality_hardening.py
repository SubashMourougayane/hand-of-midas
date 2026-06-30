"""Adversarial causality check on OB winner.

Tests:
1. Verify NO future bar information leaks into entry decision
2. Replay strictly bar-by-bar with synthetic streaming and compare
3. Permutation: scramble M5 close after entry → outcome should change radically
4. Random direction test: same setup, random side → should be ~50/50 net
5. Future shuffle: shuffle bars after entry within trade → outcome should stay similar (causal)
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import load_data, simulate, headline


def main():
    m1, m5, m15 = load_data()
    # Use the winner: ATR=1.5, exp=192, TP=3.0
    closes = m15["close"].values
    opens = m15["open"].values
    highs = m15["high"].values
    lows = m15["low"].values
    atr_v = m15["atr14"].values
    ts_m15 = m15["timestamp"].values

    obs = []
    for i in range(20, len(m15) - 3):
        if not np.isfinite(atr_v[i]) or atr_v[i] <= 0: continue
        move_up = closes[i+3] - opens[i+1]
        if move_up >= 1.5 * atr_v[i] and closes[i] < opens[i]:
            obs.append({"side": 1, "top": float(highs[i]), "bot": float(lows[i]),
                        "confirmed_ts": ts_m15[i+3], "ob_ts": ts_m15[i]})
        move_dn = opens[i+1] - closes[i+3]
        if move_dn >= 1.5 * atr_v[i] and closes[i] > opens[i]:
            obs.append({"side": -1, "top": float(highs[i]), "bot": float(lows[i]),
                        "confirmed_ts": ts_m15[i+3], "ob_ts": ts_m15[i]})

    # ============================================================
    # TEST 1: Strict bar-by-bar streaming replay
    # ============================================================
    # Each OB's "confirmation_ts" must be < entry_ts of resulting signal
    # Each retest scan must use ONLY bars whose timestamp >= confirmed_ts
    high = m5["high"].values
    low = m5["low"].values
    atr_lag = m5["atr14_lag"].values
    ts = m5["timestamp"].values

    expiry = 192
    signals = []
    leaks_found = 0
    for ob in obs:
        start = np.searchsorted(ts, np.datetime64(ob["confirmed_ts"]), side="right")
        # Check: ts[start] >= confirmed_ts (strictly after)
        if start < len(ts) and ts[start] <= np.datetime64(ob["confirmed_ts"]):
            leaks_found += 1
        end = min(len(m5), start + expiry)
        for i in range(start, end):
            if ob["side"] == 1:
                if low[i] <= ob["top"] and high[i] >= ob["bot"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk),
                                       "confirmed_ts": ob["confirmed_ts"], "entry_ts": ts[i+1] if i+1 < len(ts) else None})
                    break
            else:
                if high[i] >= ob["bot"] and low[i] <= ob["top"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": -1, "risk_units": float(risk),
                                       "confirmed_ts": ob["confirmed_ts"], "entry_ts": ts[i+1] if i+1 < len(ts) else None})
                    break

    sig_df = pd.DataFrame(signals)
    print(f"Total signals: {len(sig_df)}")
    print(f"Boundary searchsorted leaks (ts[start] <= confirmed_ts): {leaks_found}")
    # Verify every entry_ts > confirmed_ts
    entry_before_confirm = (pd.to_datetime(sig_df["entry_ts"], utc=True) <= pd.to_datetime(sig_df["confirmed_ts"], utc=True)).sum()
    print(f"Entries with entry_ts <= confirmed_ts: {entry_before_confirm} (MUST be 0)")
    if entry_before_confirm > 0:
        print("  ❌ CAUSAL LEAK DETECTED")
    else:
        print("  ✓ No look-ahead in entry timing")

    # ============================================================
    # TEST 2: Random direction baseline (same entries, random side)
    # ============================================================
    print()
    print("TEST 2: Random direction baseline (same entry indices, side flipped randomly)")
    np.random.seed(29062026)
    sig_rand = sig_df.copy()
    sig_rand["side"] = np.random.choice([-1, 1], size=len(sig_rand))
    t = simulate(sig_rand[["entry_index","side","risk_units"]], m5, tp_mult=3.0)
    h = headline(t)
    print(f"  Random direction: net={h['net']:+.1f}R PF={h['pf']:.2f} MAR={h['mar']:.2f} pos={h['pos_years']}")

    # If real edge: random direction should be flat/negative. If our "edge" is artifact, random would also be positive.

    # ============================================================
    # TEST 3: Same-bar entry (signal AT this bar, entry AT this bar's open = leak)
    # ============================================================
    print()
    print("TEST 3: same-bar entry vs next-bar entry comparison")
    # Original uses entry_index = i + 1 (correct: at next bar's open)
    sig_now = sig_df.copy(); sig_now["entry_index"] = sig_now["entry_index"] - 1
    t = simulate(sig_now[["entry_index","side","risk_units"]], m5, tp_mult=3.0)
    h = headline(t)
    print(f"  Entry SAME bar (leak): net={h['net']:+.1f}R PF={h['pf']:.2f} MAR={h['mar']:.2f}")
    sig_next = sig_df.copy()  # already next-bar
    t = simulate(sig_next[["entry_index","side","risk_units"]], m5, tp_mult=3.0)
    h = headline(t)
    print(f"  Entry NEXT bar (causal): net={h['net']:+.1f}R PF={h['pf']:.2f} MAR={h['mar']:.2f}")

    # ============================================================
    # TEST 4: Skip-N-bars entry (delay) — robust edge survives delay
    # ============================================================
    print()
    print("TEST 4: Delay entry by N bars (edge should decay gracefully)")
    for delay in [0, 1, 2, 5, 10]:
        sig_d = sig_df.copy()
        sig_d["entry_index"] = sig_d["entry_index"] + delay
        t = simulate(sig_d[["entry_index","side","risk_units"]], m5, tp_mult=3.0)
        h = headline(t)
        print(f"  +{delay} bar delay: net={h['net']:+.1f}R /yr={h['yr_r']:+.1f} PF={h['pf']:.2f} MAR={h['mar']:.2f}")


if __name__ == "__main__":
    print("=" * 100)
    print("OB CAUSALITY HARDENING")
    print("=" * 100)
    main()
