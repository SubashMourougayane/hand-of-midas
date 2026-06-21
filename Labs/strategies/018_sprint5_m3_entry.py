"""018 — Sprint 5: M3 entry timeframe instead of M15.

Hypothesis: bearishharry strategy uses D1+H4+H1 for filtering and M15 for
entry. Replacing M15 with M3 keeps the same filters (D1/H4/H1 unchanged)
but gives 5× finer entry resolution.

Expected effect:
  - Signal count: 3-5× higher (more granular engulf detection)
  - Per-trade R:R: similar (SL still anchored to sweep extreme, TP at fixed
    rr × risk)
  - PF: should hold or modestly degrade (M3 has more noise candles that
    can fake-engulf)

Coverage: Gold + Oil only. Forex M3 not available locally.
Search window for M3 engulf entry: 1 H1 (= 20 M3 bars) after H1 close.

Why limit search to next H1: same as Sprint 4 — entry must happen while
the H1 confirmation is still fresh. After 1 hour, the setup is stale.

Capital convention: yearly $5K reset, 4% risk, 5,000 unit cap. Same as
production engines and prior sprints.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from itertools import product
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.data_forex import ForexBundle, ForexPhase, _PHASE_BOUNDS, _resample
from Labs.shared.runner_forex import (
    RunResult, Signal, Trade, _slip_params_for, _yearly_stats,
)
from Labs.shared.fill_model import execute_trade
from Labs.shared.safeguards import lookahead_audit, random_baseline

_p = Path(__file__).resolve().parent / "013_bearishharry_forex.py"
_spec = importlib.util.spec_from_file_location("bh", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["bh"] = _m
_spec.loader.exec_module(_m)
BearishHarryConfig = _m.BearishHarryConfig
_daily_bias = _m._daily_bias
_h4_sweep_found = _m._h4_sweep_found
_h1_confirmation = _m._h1_confirmation


# ── M3-bundle loader for Gold + Oil ──────────────────────────────────────


def _load_m3_bundle(symbol: str, phase: ForexPhase = ForexPhase.DEVELOPMENT):
    """Load D1/H1/M3 directly from R&D's sealed gateway.

    Returns dict-style bundle with .d1, .h4, .h1, .m3 fields. NOT a ForexBundle
    because that's M15-typed.
    """
    import sys as _sys
    _rnd = Path(__file__).resolve().parent.parent.parent / "R&D"
    if str(_rnd) not in _sys.path:
        _sys.path.insert(0, str(_rnd))
    from data_split import Phase as _Phase, get_data as _get_data  # type: ignore

    rnd_phase = {
        ForexPhase.DEVELOPMENT: _Phase.DEVELOPMENT,
        ForexPhase.VALIDATION:  _Phase.VALIDATION,
        ForexPhase.HOLDOUT:     _Phase.HOLDOUT,
    }[phase]
    d1, h1, m3 = _get_data(rnd_phase, symbol)

    for df in (d1, h1, m3):
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

    h1_mid = h1[["mid_open", "mid_high", "mid_low", "mid_close", "volume"]].copy()
    d1_mid = d1[["mid_open", "mid_high", "mid_low", "mid_close", "volume"]].copy()
    h4 = _resample(h1_mid, "4h")

    start, end = _PHASE_BOUNDS[phase]
    return {
        "symbol": symbol,
        "d1":  d1_mid.loc[start:end],
        "h4":  h4.loc[start:end],
        "h1":  h1_mid.loc[start:end],
        "m3":  m3.loc[start:end],
    }


# ── M3-entry strategy ────────────────────────────────────────────────────


def _m3_entry(
    m3: pd.DataFrame,
    h1_close_ts: pd.Timestamp,
    bias: str,
    search_bars: int = 20,   # 20 × 3min = 1 H1
) -> tuple[pd.Timestamp, float, float] | None:
    """Find first M3 engulf candle within `search_bars` after h1_close_ts."""
    window_end = h1_close_ts + pd.Timedelta(minutes=3 * search_bars)
    window = m3[(m3.index > h1_close_ts) & (m3.index <= window_end)]
    if len(window) < 2:
        return None

    for i in range(1, len(window)):
        cur = window.iloc[i]
        prev = window.iloc[i - 1]
        po, pc = float(prev["mid_open"]), float(prev["mid_close"])
        co, ch, cl, cc = (
            float(cur["mid_open"]), float(cur["mid_high"]),
            float(cur["mid_low"]),  float(cur["mid_close"])
        )
        if bias == "bear":
            if cc < co and pc > po and co >= pc and cc <= po:
                return window.index[i], cc, ch  # entry, sl_extreme=high
        else:
            if cc > co and pc < po and co <= pc and cc >= po:
                return window.index[i], cc, cl
    return None


def generate_signals_m3(
    d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame, m3: pd.DataFrame,
    cfg: BearishHarryConfig,
    search_bars: int = 20,
) -> list[Signal]:
    """Same multi-TF filter as Sprint 4, but entry on M3 instead of M15."""
    signals: list[Signal] = []
    if len(h1) < 5 or len(d1) < 5 or len(h4) < 5:
        return signals

    for h1_open_ts in h1.index:
        h1_close_ts = h1_open_ts + pd.Timedelta(hours=1)

        bias = _daily_bias(d1, h1_close_ts)
        if bias == "none":
            continue
        if not _h4_sweep_found(h4, h1_close_ts, bias, cfg.sweep_lookback_hours):
            continue
        if not _h1_confirmation(
            h1, h1_close_ts, bias, cfg.h1_confirmation, cfg.min_rejection_wick_ratio
        ):
            continue

        m3_result = _m3_entry(m3, h1_close_ts, bias, search_bars=search_bars)
        if m3_result is None:
            continue
        entry_ts, entry_px, sl_extreme = m3_result

        if bias == "bear":
            sl = sl_extreme
            risk = sl - entry_px
            if risk <= 0: continue
            tp = entry_px - cfg.rr * risk
            direction = "short"
        else:
            sl = sl_extreme
            risk = entry_px - sl
            if risk <= 0: continue
            tp = entry_px + cfg.rr * risk
            direction = "long"

        # Max hold: same wall-clock as Sprint 4 (96 M15 = 24h = 480 M3 bars)
        max_bars_m3 = cfg.max_bars * 5
        signals.append(Signal(
            entry_bar_ts=entry_ts, direction=direction,
            entry=entry_px, sl=sl, tp=tp,
            max_bars=max_bars_m3,
            metadata={"bias": bias, "tf": "m3"},
        ))
    return signals


# ── Runner using M3 instead of M15 ───────────────────────────────────────


def run_strategy_m3(
    strategy_fn,
    bundle: dict,
    config_label: str = "",
    *,
    starting_capital: float = 5_000.0,
    risk_pct: float = 4.0,
    max_units: float = 5_000.0,
) -> RunResult:
    signals = strategy_fn(bundle["d1"], bundle["h4"], bundle["h1"], bundle["m3"])
    slip_base, slip_range_coef = _slip_params_for(bundle["symbol"])
    m3 = bundle["m3"]
    trades: list[Trade] = []
    for sig in signals:
        try:
            bar_idx = m3.index.get_loc(sig.entry_bar_ts)
        except KeyError:
            continue
        result = execute_trade(
            df=m3, bar_start=bar_idx, entry=sig.entry, sl=sig.sl, tp=sig.tp,
            direction=sig.direction, max_bars=sig.max_bars,
            slip_base=slip_base, slip_range_coef=slip_range_coef,
        )
        if result is None: continue
        trades.append(Trade(signal=sig, result=result))

    pnls = [
        t.result.pnl_per_unit * (
            min(starting_capital * (risk_pct / 100.0)
                / max(abs(t.signal.entry - t.signal.sl), 1e-9), max_units)
        ) for t in trades
    ]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    total_pnl = float(sum(pnls))
    gw = float(sum(p for p in pnls if p > 0))
    gl = float(abs(sum(p for p in pnls if p <= 0)))
    pf = gw / gl if gl > 0 else float("inf")
    by_year = _yearly_stats(trades, starting_capital, risk_pct, max_units)
    max_dd = max((y["dd_pct"] for y in by_year.values()), default=0.0)
    return RunResult(
        symbol=bundle["symbol"], config_label=config_label,
        trades=trades, total_signals=len(signals), total_trades=len(trades),
        wins=wins, losses=losses,
        win_rate=wins / len(trades) if trades else 0.0,
        total_pnl=round(total_pnl, 2),
        profit_factor=round(pf, 3),
        max_dd_pct_yearly_worst=round(max_dd, 2),
        by_year=by_year,
    )


# ── Sweep + walk-forward per asset ───────────────────────────────────────


GRID = {
    "sweep_lookback_hours": [12, 24],
    "h1_confirmation":      ["rejection_wick", "engulf"],
    "m15_entry":            ["engulf_close"],   # only one entry style on M3
    "rr":                   [1.5, 2.0, 3.0],
}


def _all_configs() -> list[BearishHarryConfig]:
    keys = list(GRID.keys())
    return [BearishHarryConfig(**dict(zip(keys, vals))) for vals in product(*GRID.values())]


def _config_label(cfg: BearishHarryConfig) -> str:
    return f"swp{cfg.sweep_lookback_hours}_{cfg.h1_confirmation[:3]}_rr{cfg.rr}"


def _slice_bundle(b: dict, start, end) -> dict:
    return {
        "symbol": b["symbol"],
        "d1": b["d1"].loc[start:end],
        "h4": b["h4"].loc[start:end],
        "h1": b["h1"].loc[start:end],
        "m3": b["m3"].loc[start:end],
    }


def run_asset(symbol: str, search_bars: int = 20) -> dict:
    """Returns a dict of results for the asset."""
    bundle = _load_m3_bundle(symbol)
    print()
    print("=" * 78)
    print(f"  Sprint 5 — bearishharry M3 entry on {symbol} (search_bars={search_bars})")
    print("=" * 78)
    print(f"  Dev window: {bundle['m3'].index[0]} → {bundle['m3'].index[-1]}")
    print(f"  M3 bars: {len(bundle['m3']):,}  H1: {len(bundle['h1']):,}  D1: {len(bundle['d1'])}")
    print()

    rows = []
    configs = _all_configs()
    for cfg in configs:
        fn = lambda d1_, h4_, h1_, m3_, c=cfg: generate_signals_m3(d1_, h4_, h1_, m3_, c, search_bars)
        r = run_strategy_m3(fn, bundle, config_label=_config_label(cfg))
        rows.append({
            "symbol": symbol,
            "sweep_lookback_hours": cfg.sweep_lookback_hours,
            "h1_confirmation": cfg.h1_confirmation,
            "rr": cfg.rr,
            "trades": r.total_trades,
            "wins": r.wins,
            "win_rate": round(r.win_rate, 4),
            "pf": r.profit_factor,
            "pnl": r.total_pnl,
            "max_dd_pct": r.max_dd_pct_yearly_worst,
        })

    survivors = [r for r in rows if r["pf"] >= 1.10 and r["trades"] >= 30]
    print(f"  Dev configs ({len(configs)}): {len(survivors)} pass PF≥1.10 + n≥30")
    for s in sorted(survivors, key=lambda x: -x["pf"]):
        print(f"    {s['sweep_lookback_hours']:>3}h {s['h1_confirmation']:<16} rr={s['rr']}  "
              f"PF={s['pf']:.3f}  n={s['trades']:>4}  P&L=${s['pnl']:>10,.2f}  DD={s['max_dd_pct']:.2f}%")

    # Walk-forward
    train_start = pd.Timestamp("2019-09-26"); train_end = pd.Timestamp("2022-12-31 23:59:59")
    val_start   = pd.Timestamp("2023-01-01"); val_end   = pd.Timestamp("2023-12-31 23:59:59")
    train_b = _slice_bundle(bundle, train_start, train_end)
    val_b   = _slice_bundle(bundle, val_start, val_end)

    wf_rows = []
    for s in survivors:
        cfg = BearishHarryConfig(
            sweep_lookback_hours=s["sweep_lookback_hours"],
            h1_confirmation=s["h1_confirmation"],
            m15_entry="engulf_close",
            rr=s["rr"],
        )
        fn = lambda d1_, h4_, h1_, m3_, c=cfg: generate_signals_m3(d1_, h4_, h1_, m3_, c, search_bars)
        rt = run_strategy_m3(fn, train_b)
        rv = run_strategy_m3(fn, val_b)
        wf_rows.append({
            "config": _config_label(cfg),
            "train_pf": rt.profit_factor, "train_n": rt.total_trades, "train_pnl": rt.total_pnl,
            "val_pf":   rv.profit_factor, "val_n":   rv.total_trades, "val_pnl":   rv.total_pnl,
        })
    wf_pass = [w for w in wf_rows if w["train_pf"] >= 1.10 and w["val_pf"] >= 1.10]
    print(f"\n  Walk-forward: {len(wf_pass)}/{len(wf_rows)} survivors pass BOTH train+val PF≥1.10")
    for w in sorted(wf_pass, key=lambda x: -x["val_pf"]):
        print(f"    ✓ {w['config']:<26}  Train PF={w['train_pf']:.2f} (n={w['train_n']:>3})  "
              f"Val PF={w['val_pf']:.2f} (n={w['val_n']:>3})")
    for w in sorted([x for x in wf_rows if x not in wf_pass], key=lambda x: -x["val_pf"]):
        print(f"    ✗ {w['config']:<26}  Train PF={w['train_pf']:.2f} (n={w['train_n']:>3})  "
              f"Val PF={w['val_pf']:.2f} (n={w['val_n']:>3})")

    if not wf_pass:
        print(f"\n  {symbol}: NO WALK-FORWARD SURVIVOR")
        return {"symbol": symbol, "rows": rows, "wf_rows": wf_rows, "top": None}

    # Safeguards on survivors
    print(f"\n  Running safeguards on {len(wf_pass)} survivors...")
    for w in wf_pass:
        cfg = next(BearishHarryConfig(
            sweep_lookback_hours=s["sweep_lookback_hours"],
            h1_confirmation=s["h1_confirmation"],
            m15_entry="engulf_close",
            rr=s["rr"],
        ) for s in survivors if _config_label(BearishHarryConfig(
            sweep_lookback_hours=s["sweep_lookback_hours"],
            h1_confirmation=s["h1_confirmation"],
            m15_entry="engulf_close",
            rr=s["rr"],
        )) == w["config"])
        fn3 = lambda d1_, h1_, m3_, c=cfg, h4=bundle["h4"]: generate_signals_m3(d1_, h4, h1_, m3_, c, search_bars)
        la = lookahead_audit(fn3, (bundle["d1"], bundle["h1"], bundle["m3"]))
        rb = random_baseline((bundle["d1"], bundle["h1"], bundle["m3"]), n_trades=2000)
        la_l = "PASS" if la.passed else "FAIL"
        rb_l = "PASS" if rb.passed else "FAIL"
        print(f"    {w['config']:<26}  lookahead={la_l}  random_baseline={rb_l}")

    # Per-year for top val-PF
    top = max(wf_pass, key=lambda x: x["val_pf"])
    print()
    print(f"  Per-year detail for top {symbol}: {top['config']}")
    print(f"  {'Year':<6} {'Trades':<8} {'Wins':<6} {'WR%':<8} {'P&L':>14} {'DD%':>8}")
    cfg = next(BearishHarryConfig(
        sweep_lookback_hours=s["sweep_lookback_hours"],
        h1_confirmation=s["h1_confirmation"],
        m15_entry="engulf_close",
        rr=s["rr"],
    ) for s in survivors if _config_label(BearishHarryConfig(
        sweep_lookback_hours=s["sweep_lookback_hours"],
        h1_confirmation=s["h1_confirmation"],
        m15_entry="engulf_close",
        rr=s["rr"],
    )) == top["config"])
    fn = lambda d1_, h4_, h1_, m3_, c=cfg: generate_signals_m3(d1_, h4_, h1_, m3_, c, search_bars)
    r_top = run_strategy_m3(fn, bundle)
    pair_pnl = 0.0; pair_trades = 0
    for y in sorted(r_top.by_year.keys()):
        s = r_top.by_year[y]
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0.0
        print(f"  {y:<6} {s['trades']:<8} {s['wins']:<6} {wr:<8.1f} ${s['pnl']:>11,.2f}  {s['dd_pct']:>7.2f}")
        pair_pnl += s["pnl"]; pair_trades += s["trades"]
    years = len(r_top.by_year)
    print(f"  TOTAL  {pair_trades:<8}        {'':<8} ${pair_pnl:>11,.2f}  ({years}y → ${pair_pnl/years:,.2f}/yr)  PF={r_top.profit_factor:.2f}")

    return {"symbol": symbol, "rows": rows, "wf_rows": wf_rows, "top": top, "top_run": r_top}


def main() -> None:
    out_dir = _REPO_ROOT / "Labs" / "results"
    print()
    print("█" * 78)
    print("  SPRINT 5 — M3 entry timeframe on Gold + Brent")
    print("█" * 78)

    all_rows = []
    summaries = []
    for sym in ["XAU_USD", "BCO_USD"]:
        result = run_asset(sym)
        all_rows.extend(result["rows"])
        summaries.append(result)

    # Save dev grid CSV
    out_path = out_dir / "sprint_5_m3.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader(); w.writerows(all_rows)
    print(f"\n  Wrote {out_path}")

    # Cross-asset comparison
    print()
    print("█" * 78)
    print("  Sprint 4 (M15) vs Sprint 5 (M3) — top survivor per asset")
    print("█" * 78)
    print(f"  {'Asset':<10} {'TF':<5} {'Config':<26} {'Trades':<8} {'PF':<6} "
          f"{'Total $':>14} {'$/yr':>12} {'DD%':>7}")
    sprint4_baseline = {
        "XAU_USD": dict(tf="M15", config="swp12_rej_rr3.0", trades=49,  pf=2.42, total=9308.10, per_yr=1861.62, dd=22.7),
        "BCO_USD": dict(tf="M15", config="swp12_eng_rr3.0", trades=31,  pf=2.15, total=6118.22, per_yr=1223.64, dd=27.1),
    }
    for s in summaries:
        bl = sprint4_baseline[s["symbol"]]
        print(f"  {s['symbol']:<10} {bl['tf']:<5} {bl['config']:<26} "
              f"{bl['trades']:<8} {bl['pf']:<6.2f} ${bl['total']:>11,.2f}  ${bl['per_yr']:>9,.2f}  {bl['dd']:>6.1f}")
        if s["top"]:
            tr = s["top_run"]
            total = sum(y["pnl"] for y in tr.by_year.values())
            yrs = len(tr.by_year)
            dd  = max((y["dd_pct"] for y in tr.by_year.values()), default=0.0)
            print(f"  {s['symbol']:<10} {'M3':<5} {s['top']['config']:<26} "
                  f"{tr.total_trades:<8} {tr.profit_factor:<6.2f} ${total:>11,.2f}  ${total/yrs:>9,.2f}  {dd:>6.1f}")
        else:
            print(f"  {s['symbol']:<10} {'M3':<5} NO WF SURVIVOR")
        print()


if __name__ == "__main__":
    main()
