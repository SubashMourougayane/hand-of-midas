"""006 — Donchian Channel Breakout: parameter sweep with walk-forward.

Sprint 2-A. Builds on Strategy #004 (which lost at default 20/10 RR=2).
Sweep on Train (2019-2022), pick top 3 by Train PF, run unchanged on
Validate (2023).

Locked discipline:
- Configs scanned on Train only
- Top 3 selected by Train PF (no peeking at Validate)
- Selected configs run unchanged on Validate
- Best Validate PF wins (if PF > 1.10 — else "none survived")
- Promotion bar same as Sprint 1: PF > 1.10 AND DD < 50% AND lookahead PASS AND random PASS

Sweep grid (deliberately small to avoid p-hacking):
- breakout_lookback : [10, 20, 50, 100]   (H1 bars)
- sl_lookback       : [5, 10, 20]
- reward_to_risk    : [1.0, 2.0, 3.0]
Total: 4 × 3 × 3 = 36 configs.

If 36-config sweep finds a winner that doesn't survive Validate, the
finding is "Donchian doesn't generalise". If a config survives both,
that's a candidate for sprint 3 (proper out-of-sample on R&D's 2024
validation slice — separate decision).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.runner import Signal, run_strategy, RunResult


@dataclass(frozen=True)
class DonchianConfig:
    breakout_lookback: int = 20
    sl_lookback: int = 10
    reward_to_risk: float = 2.0
    max_bars: int = 240
    one_trade_per_day: bool = True


def generate_signals(
    d1: pd.DataFrame,
    h1: pd.DataFrame,
    m3: pd.DataFrame,
    cfg: DonchianConfig | None = None,
) -> list[Signal]:
    """Donchian breakout. Same logic as Strategy #004 but parameterised."""
    if cfg is None:
        cfg = DonchianConfig()

    signals: list[Signal] = []

    h1_high = h1["mid_high"].rolling(cfg.breakout_lookback).max().shift(1)
    h1_low = h1["mid_low"].rolling(cfg.breakout_lookback).min().shift(1)
    h1_sl_high = h1["mid_high"].rolling(cfg.sl_lookback).max().shift(1)
    h1_sl_low = h1["mid_low"].rolling(cfg.sl_lookback).min().shift(1)

    last_fire_day = None

    for ts, bar in h1.iterrows():
        if cfg.one_trade_per_day:
            day = ts.normalize()
            if last_fire_day == day:
                continue

        breakout_high = h1_high.loc[ts]
        breakout_low = h1_low.loc[ts]
        sl_high = h1_sl_high.loc[ts]
        sl_low = h1_sl_low.loc[ts]
        if pd.isna(breakout_high) or pd.isna(breakout_low):
            continue

        h_close = float(bar["mid_close"])
        h_high = float(bar["mid_high"])
        h_low = float(bar["mid_low"])

        direction = None
        entry_price = None
        sl = None

        if h_high > breakout_high and h_close > breakout_high:
            direction = "long"
            entry_price = float(bar["ask_close"])
            sl = float(sl_low)
        elif h_low < breakout_low and h_close < breakout_low:
            direction = "short"
            entry_price = float(bar["bid_close"])
            sl = float(sl_high)

        if direction is None:
            continue

        h1_close_ts = ts + pd.Timedelta(hours=1)
        m3_after_close = m3[m3.index >= h1_close_ts]
        if m3_after_close.empty:
            continue
        entry_bar_ts = m3_after_close.index[0]

        risk = abs(entry_price - sl)
        if risk <= 0:
            continue

        if direction == "long":
            tp = entry_price + cfg.reward_to_risk * risk
        else:
            tp = entry_price - cfg.reward_to_risk * risk

        signals.append(Signal(
            entry_bar_ts=entry_bar_ts,
            direction=direction,
            entry=entry_price,
            sl=sl,
            tp=tp,
            max_bars=cfg.max_bars,
            metadata={
                "strategy": "DONCHIAN_SWEEP",
                "lb": cfg.breakout_lookback,
                "sl_lb": cfg.sl_lookback,
                "rr": cfg.reward_to_risk,
            },
        ))
        if cfg.one_trade_per_day:
            last_fire_day = ts.normalize()

    return sorted(signals, key=lambda s: s.entry_bar_ts)


# ── Sweep harness ─────────────────────────────────────────────────────────


def main() -> None:
    from Labs.shared.data import get_brent
    from Labs.shared.runner import print_report
    from Labs.shared.safeguards import (
        lookahead_audit, random_baseline, print_safeguard_report,
    )
    from Labs.shared.walk_forward import split_dev, describe_split

    print("Loading dev data via sealed gateway...")
    data = get_brent()
    print(f"  Total dev: D1={len(data[0]):,}  H1={len(data[1]):,}  M3={len(data[2]):,}")
    wf = split_dev(data)
    print(describe_split(wf))

    # Build sweep grid
    breakout_lbs = [10, 20, 50, 100]
    sl_lbs = [5, 10, 20]
    rrs = [1.0, 2.0, 3.0]
    total = len(breakout_lbs) * len(sl_lbs) * len(rrs)
    print(f"\nSweeping {total} configs on Train ({len(breakout_lbs)} × {len(sl_lbs)} × {len(rrs)})...")

    train_results: list[tuple[DonchianConfig, RunResult]] = []

    for lb in breakout_lbs:
        for sl_lb in sl_lbs:
            for rr in rrs:
                if sl_lb >= lb:
                    # SL lookback must be shorter than breakout lookback
                    continue
                cfg = DonchianConfig(
                    breakout_lookback=lb,
                    sl_lookback=sl_lb,
                    reward_to_risk=rr,
                )
                fn = lambda d1_, h1_, m3_, c=cfg: generate_signals(d1_, h1_, m3_, c)
                r = run_strategy(fn, wf.train)
                train_results.append((cfg, r))
                print(f"  lb={lb:>3}  sl={sl_lb:>3}  rr={rr:>3.1f}  →  "
                      f"trades={r.total_trades:>4}  WR={r.win_rate*100:>5.2f}%  "
                      f"PF={r.profit_factor:>6.3f}  P&L=${r.total_pnl:>+10,.2f}  "
                      f"DD={r.max_dd_pct_yearly_worst:>5.2f}%")

    # Top 3 by PF, with min trade count to avoid noise
    valid = [(c, r) for c, r in train_results if r.total_trades >= 50]
    valid.sort(key=lambda cr: cr[1].profit_factor, reverse=True)
    top_3 = valid[:3]

    print(f"\n=== Top 3 configs on Train (≥ 50 trades) ===")
    for cfg, r in top_3:
        print(f"  lb={cfg.breakout_lookback:>3}  sl={cfg.sl_lookback:>3}  rr={cfg.reward_to_risk:>3.1f}"
              f"  →  Train PF={r.profit_factor:.3f}  Train P&L=${r.total_pnl:+,.2f}")

    # ───── Run top 3 on Validate UNCHANGED ─────
    print(f"\n=== Running top 3 on Validate (2023, unseen) ===")
    final_picks: list[tuple[DonchianConfig, RunResult, RunResult]] = []
    for cfg, train_r in top_3:
        fn = lambda d1_, h1_, m3_, c=cfg: generate_signals(d1_, h1_, m3_, c)
        val_r = run_strategy(fn, wf.validate)
        final_picks.append((cfg, train_r, val_r))
        print(f"  lb={cfg.breakout_lookback:>3}  sl={cfg.sl_lookback:>3}  rr={cfg.reward_to_risk:>3.1f}"
              f"  →  Validate trades={val_r.total_trades:>3}  "
              f"WR={val_r.win_rate*100:>5.2f}%  "
              f"PF={val_r.profit_factor:>6.3f}  "
              f"P&L=${val_r.total_pnl:>+10,.2f}  "
              f"DD={val_r.max_dd_pct_yearly_worst:>5.2f}%")

    # Identify the best Validate PF
    best = max(final_picks, key=lambda x: x[2].profit_factor)
    cfg, train_r, val_r = best
    print(f"\n=== Best Validate config ===")
    print(f"  lb={cfg.breakout_lookback}  sl={cfg.sl_lookback}  rr={cfg.reward_to_risk}")
    print(f"  Train  : PF={train_r.profit_factor:.3f}  P&L=${train_r.total_pnl:+,.2f}")
    print(f"  Validate: PF={val_r.profit_factor:.3f}  P&L=${val_r.total_pnl:+,.2f}")

    # Promotion bar — only run safeguards if Validate PF > 1.10
    if val_r.profit_factor < 1.10:
        print(f"\n  ==> NO PROMOTION  (Validate PF {val_r.profit_factor:.3f} below 1.10 threshold)")
        return

    print(f"\n  Validate PF > 1.10. Running safeguards on Validate slice...")
    fn_best = lambda d1_, h1_, m3_, c=cfg: generate_signals(d1_, h1_, m3_, c)
    la = lookahead_audit(fn_best, wf.validate)
    rb = random_baseline(wf.validate, n_trades=max(val_r.total_trades, 200))
    trusted = print_safeguard_report(f"006 — Donchian best lb={cfg.breakout_lookback}", la, rb)
    if val_r.max_dd_pct_yearly_worst >= 50:
        print(f"  ==> NO PROMOTION  (Validate DD {val_r.max_dd_pct_yearly_worst:.1f}% ≥ 50%)")
        return
    if not trusted:
        print(f"  ==> NO PROMOTION  (safeguards failed)")
        return

    print(f"\n  ==> CANDIDATE FOR SPRINT 3 (R&D validation 2024 + holdout 2025-26)")


if __name__ == "__main__":
    main()
