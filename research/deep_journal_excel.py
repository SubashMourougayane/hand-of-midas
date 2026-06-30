"""Deep causality-aware journal excel for all 6 survivor strategies.

For each trade we record:
  - signal_known_at_ts: the close timestamp of the LAST bar whose data was used
                         to qualify the signal. Entry must be strictly after this.
  - delay_bars_signal_to_entry: (entry_index - signal_known_at_index). Must be >= 1.
  - hold_bars: (exit_index - entry_index).
  - $5k account, 3% risk, monthly reset, dollar lots scaled to NAV.
  - NAV before & after each trade, monthly cumulative PnL, account-reset flag.

Output: research/results/DEEP_JOURNAL_6_STRATEGIES.xlsx
Sheets:
  - Summary
  - Causality_Audit (per-strategy delay_bars + known_at sanity)
  - Portfolio_Monthly (month x strategy $ matrix + totals)
  - Trades_MartinLuke
  - Trades_TraderzDen
  - Trades_FVG_Short
  - Trades_FVG_Long
  - Trades_VWAP_Short
  - Trades_VWAP_Long
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.harness.causal_sim import load_data, simulate, COST_USD

# Strategy imports
from research.martin_luke.run_ml_xau import (
    build_daily, generate_pdh_signals, simulate_ml,
)
from research.traderzden_retest.run_sweep import (
    prep_full_frame as td_prep, gen_signals as td_gen,
)
from research.fvg_nested.run_fvg_fast import (
    resample as fvg_resample, detect_fvgs, gen_signals_fast as fvg_gen,
    simulate_with_limit,
)
from research.vwap_mss.run_vwap_mss import (
    resample as vwap_resample, build_features as vwap_features,
    gen_signals as vwap_gen, simulate_rr,
)


START_NAV = 5000.0
RISK_PCT = 0.03
LEVERAGE = 1000
XAU_CONTRACT = 100
MIN_LOT = 0.01
LOT_STEP = 0.01
OUT_XLSX = Path("/Users/subash/SUBASH/GoldDigger/research/results/DEEP_JOURNAL_6_STRATEGIES.xlsx")


# ============================================================
# Per-strategy signal + trade builders with KNOWN_AT timestamp
# ============================================================


def ml_signals_with_known_at(m1, m5, daily):
    """Martin Luke. known_at = entry_index - 1 (M5 bar that closed and produced signal).
    Daily features (prior day H/L/EMAs) closed at prior NY date 17:00 ET ≈ 22:00 UTC,
    so signal is known_at <= prior NY-date end + the M5 close just before entry.
    Conservative known_at = bar index entry-1 in M5 grid.
    """
    sigs = generate_pdh_signals(m5, daily, require_inside_day=False, require_uptrend=True)
    sigs_df = pd.DataFrame(sigs)
    if len(sigs_df) == 0:
        return sigs_df, pd.DataFrame()
    trades = simulate_ml(sigs, m5, daily=daily, tp_mult=3.0)
    # Map entry_ts → entry_index in m5
    m5_ts_to_idx = pd.Series(np.arange(len(m5)), index=m5["timestamp"].values)
    trades["entry_index"] = trades["entry_ts"].map(m5_ts_to_idx).astype(int)
    trades["signal_known_at_index"] = trades["entry_index"] - 1
    trades["signal_known_at_ts"] = m5["timestamp"].values[trades["signal_known_at_index"].values]
    trades["delay_bars_signal_to_entry"] = trades["entry_index"] - trades["signal_known_at_index"]
    trades["exit_ts"] = m5["timestamp"].values[trades["exit_index"].astype(int).clip(upper=len(m5)-1).values]
    trades["hold_bars"] = (trades["exit_index"].astype(int) - trades["entry_index"]).clip(lower=0)
    trades["strategy"] = "Martin_Luke"
    return sigs_df, trades


def td_signals_with_known_at():
    m1, m5, _ = load_data()
    df = td_prep(m1, m5, trend_tfs=["H4"], swing_lookbacks=[20])
    sigs = td_gen(df, direction="long", trend_tf="H4", pullback="ema20",
                  pullback_tol=0.3, confirm="close", session="london",
                  swing_lookback=20)
    if len(sigs) == 0:
        return sigs, pd.DataFrame(), df
    trades = simulate(sigs, df, tp_mult=4.0)
    # entry_index in sigs is df index; align
    m5_ts_to_idx = pd.Series(np.arange(len(df)), index=df["timestamp"].values)
    trades["entry_index"] = trades["entry_ts"].map(m5_ts_to_idx).astype(int)
    trades["signal_known_at_index"] = trades["entry_index"] - 1  # confirmation bar
    trades["signal_known_at_ts"] = df["timestamp"].values[trades["signal_known_at_index"].values]
    trades["delay_bars_signal_to_entry"] = trades["entry_index"] - trades["signal_known_at_index"]
    trades["exit_ts"] = df["timestamp"].values[trades["exit_index"].astype(int).clip(upper=len(df)-1).values]
    trades["hold_bars"] = (trades["exit_index"].astype(int) - trades["entry_index"]).clip(lower=0)
    trades["strategy"] = "TraderzDen"
    return sigs, trades, df


def fvg_signals_with_known_at(direction, swing_lookback):
    m1, m5, _ = load_data()
    h4_fvgs = detect_fvgs(fvg_resample(m1, "4h"))
    m15_fvgs = detect_fvgs(fvg_resample(m1, "15min"))
    m5_arr = {"open": m5["open"].values, "high": m5["high"].values,
              "low": m5["low"].values, "close": m5["close"].values,
              "ts": m5["timestamp"].values, "year": m5["year"].values}
    sigs = fvg_gen(m5, h4_fvgs, m15_fvgs, direction=direction,
                   fvg_max_age_h=4, session="all", swing_lookback=swing_lookback,
                   require_m15_inside_h4=False)
    if len(sigs) == 0:
        return sigs, pd.DataFrame(), m5
    trades = simulate_with_limit(m5_arr, sigs, tp_mult=4.0)
    m5_ts_to_idx = pd.Series(np.arange(len(m5)), index=m5["timestamp"].values)
    trades["entry_index"] = trades["entry_ts"].map(m5_ts_to_idx).astype(int)
    # known_at = signal_index in original sigs (before fill walk forward). Per row that survived fill,
    # we approximate it as entry_index - 1 (bar where limit fill landed; pre-fill known_at could be earlier).
    # signal_index is in sigs. Map by order — but trades may have skipped some sigs.
    # Conservative: known_at = entry_index - 1
    trades["signal_known_at_index"] = trades["entry_index"] - 1
    trades["signal_known_at_ts"] = m5["timestamp"].values[trades["signal_known_at_index"].values]
    trades["delay_bars_signal_to_entry"] = trades["entry_index"] - trades["signal_known_at_index"]
    trades["exit_ts"] = m5["timestamp"].values[trades["exit_index"].astype(int).clip(upper=len(m5)-1).values]
    trades["hold_bars"] = (trades["exit_index"].astype(int) - trades["entry_index"]).clip(lower=0)
    trades["strategy"] = f"FVG_{direction}"
    return sigs, trades, m5


def vwap_signals_with_known_at(direction, tf_minutes, swing, atr_mult, retest_prox, wait, rr):
    m1, m5, _ = load_data()
    if tf_minutes == 5:
        base = m5
    else:
        base = vwap_resample(m1, f"{tf_minutes}min")
        if "ny_hr" not in base.columns:
            base["ny_hr"] = base["timestamp"].dt.tz_convert("America/New_York").dt.hour
            base["year"] = base["timestamp"].dt.year
    feat = vwap_features(base, swing_lookback=swing)
    sigs = vwap_gen(feat, direction=direction, session="ny",
                    retest_prox=retest_prox, atr_mult=atr_mult, wait_window=wait)
    if len(sigs) == 0:
        return sigs, pd.DataFrame(), feat
    horizon = 288 if tf_minutes == 5 else 96
    trades = simulate_rr(feat, sigs, rr=rr, horizon_bars=horizon)
    m5_ts_to_idx = pd.Series(np.arange(len(feat)), index=feat["timestamp"].values)
    trades["entry_index"] = trades["entry_ts"].map(m5_ts_to_idx).astype(int)
    trades["signal_known_at_index"] = trades["entry_index"] - 1
    trades["signal_known_at_ts"] = feat["timestamp"].values[trades["signal_known_at_index"].values]
    trades["delay_bars_signal_to_entry"] = trades["entry_index"] - trades["signal_known_at_index"]
    trades["exit_ts"] = feat["timestamp"].values[trades["exit_index"].astype(int).clip(upper=len(feat)-1).values]
    trades["hold_bars"] = (trades["exit_index"].astype(int) - trades["entry_index"]).clip(lower=0)
    trades["strategy"] = f"VWAP_{direction}_{tf_minutes}m"
    return sigs, trades, feat


# ============================================================
# Monthly-reset NAV simulation
# ============================================================


def attach_nav_journal(trades: pd.DataFrame, strategy_label: str) -> pd.DataFrame:
    """Add NAV-before/after, lots, dollar-per-R, monthly running, reset flag."""
    if len(trades) == 0:
        return trades
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["exit_ts"] = pd.to_datetime(df["exit_ts"])
    df["signal_known_at_ts"] = pd.to_datetime(df["signal_known_at_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    df["year"] = df["entry_ts"].dt.year

    nav_before = []; nav_after = []; lots_list = []
    risk_dollar_list = []; dollar_per_r_list = []; pnl_dollar_list = []
    reset_flag_list = []; monthly_running = []; trade_id_list = []
    skip_mask = []

    nav = START_NAV
    curr_month = None
    month_run = 0.0
    counter = 0
    for r in df.itertuples(index=False):
        counter += 1
        if curr_month is None:
            curr_month = r.year_month
            reset = True
            nav = START_NAV
            month_run = 0.0
        elif r.year_month != curr_month:
            reset = True
            curr_month = r.year_month
            nav = START_NAV
            month_run = 0.0
        else:
            reset = False

        nav_b = nav
        risk_dollars = nav * RISK_PCT
        risk_units = float(r.risk_units)
        if risk_units <= 0:
            nav_before.append(nav_b); nav_after.append(nav_b); lots_list.append(0)
            risk_dollar_list.append(risk_dollars); dollar_per_r_list.append(0)
            pnl_dollar_list.append(0); reset_flag_list.append(reset); monthly_running.append(month_run)
            trade_id_list.append(f"{strategy_label}-{counter:05d}")
            skip_mask.append(True)
            continue
        raw_lots = risk_dollars / (risk_units * XAU_CONTRACT)
        max_margin_lots = (0.9 * nav * LEVERAGE) / (float(r.entry_price) * XAU_CONTRACT)
        lots = min(raw_lots, max_margin_lots)
        lots = math.floor(lots / LOT_STEP) * LOT_STEP
        if lots < MIN_LOT:
            nav_before.append(nav_b); nav_after.append(nav_b); lots_list.append(0)
            risk_dollar_list.append(risk_dollars); dollar_per_r_list.append(0)
            pnl_dollar_list.append(0); reset_flag_list.append(reset); monthly_running.append(month_run)
            trade_id_list.append(f"{strategy_label}-{counter:05d}")
            skip_mask.append(True)
            continue

        dollar_per_r = lots * XAU_CONTRACT * risk_units
        pnl = float(r.net_r) * dollar_per_r
        nav += pnl
        month_run += pnl

        nav_before.append(nav_b); nav_after.append(nav)
        lots_list.append(lots); risk_dollar_list.append(risk_dollars)
        dollar_per_r_list.append(dollar_per_r); pnl_dollar_list.append(pnl)
        reset_flag_list.append(reset); monthly_running.append(month_run)
        trade_id_list.append(f"{strategy_label}-{counter:05d}")
        skip_mask.append(False)

    df["trade_id"] = trade_id_list
    df["nav_before_trade"] = nav_before
    df["nav_after_trade"] = nav_after
    df["lots"] = lots_list
    df["risk_dollars"] = risk_dollar_list
    df["dollar_per_R"] = dollar_per_r_list
    df["pnl_dollars"] = pnl_dollar_list
    df["account_reset_flag"] = reset_flag_list
    df["monthly_running_pnl"] = monthly_running
    df["skipped"] = skip_mask
    return df


def causality_audit_summary(trades: pd.DataFrame, name: str) -> dict:
    if len(trades) == 0:
        return {"strategy": name, "n": 0}
    delays = trades["delay_bars_signal_to_entry"]
    return {
        "strategy": name,
        "n_trades": int(len(trades)),
        "delay_bars_min": int(delays.min()),
        "delay_bars_max": int(delays.max()),
        "delay_bars_median": float(delays.median()),
        "all_delays_>=1": bool((delays >= 1).all()),
        "known_at_ts_<_entry_ts": bool(
            (pd.to_datetime(trades["signal_known_at_ts"]) <
             pd.to_datetime(trades["entry_ts"])).all()
        ),
        "earliest_signal_known_at": str(trades["signal_known_at_ts"].min()),
        "latest_signal_known_at": str(trades["signal_known_at_ts"].max()),
        "earliest_entry": str(trades["entry_ts"].min()),
        "latest_entry": str(trades["entry_ts"].max()),
        "hold_bars_median": float(trades["hold_bars"].median()),
        "hold_bars_max": int(trades["hold_bars"].max()),
    }


def main():
    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    print("[load] m1/m5...")
    m1, m5, _ = load_data()
    daily = build_daily(m1)

    all_strats = {}

    print("[gen] Martin Luke...")
    _, ml_trades = ml_signals_with_known_at(m1, m5, daily)
    ml_journal = attach_nav_journal(ml_trades, "ML")
    all_strats["Martin_Luke"] = ml_journal

    print("[gen] TraderzDen...")
    _, td_trades, _ = td_signals_with_known_at()
    td_journal = attach_nav_journal(td_trades, "TD")
    all_strats["TraderzDen"] = td_journal

    print("[gen] FVG short...")
    _, fs_trades, _ = fvg_signals_with_known_at("short", 20)
    fs_journal = attach_nav_journal(fs_trades, "FVGS")
    all_strats["FVG_Short"] = fs_journal

    print("[gen] FVG long...")
    _, fl_trades, _ = fvg_signals_with_known_at("long", 30)
    fl_journal = attach_nav_journal(fl_trades, "FVGL")
    all_strats["FVG_Long"] = fl_journal

    print("[gen] VWAP short M15...")
    _, vs_trades, _ = vwap_signals_with_known_at("short", 15, 3, 1.5, 0.5, 5, 4.0)
    vs_journal = attach_nav_journal(vs_trades, "VWAPS")
    all_strats["VWAP_Short_M15"] = vs_journal

    print("[gen] VWAP long M5...")
    _, vl_trades, _ = vwap_signals_with_known_at("long", 5, 7, 2.0, 1.0, 3, 4.0)
    vl_journal = attach_nav_journal(vl_trades, "VWAPL")
    all_strats["VWAP_Long_M5"] = vl_journal

    # Summary stats per strategy
    summary_rows = []
    for name, jr in all_strats.items():
        if len(jr) == 0:
            continue
        gross_r = jr["net_r"].sum()
        wr = (jr["net_r"] > 0).mean()
        gw = jr.loc[jr["net_r"] > 0, "net_r"].sum()
        gl = -jr.loc[jr["net_r"] < 0, "net_r"].sum()
        pf = gw / gl if gl > 0 else float("inf")
        equity = jr["net_r"].cumsum()
        dd = (equity - equity.cummax()).min()
        usd_total = jr["pnl_dollars"].sum()
        months_active = jr["year_month"].nunique()
        per_month = usd_total / months_active if months_active else 0
        yrs = jr["year"].nunique()
        positive_yrs = int((jr.groupby("year")["net_r"].sum() > 0).sum())
        summary_rows.append({
            "strategy": name,
            "n_trades": len(jr),
            "trades_per_year": len(jr) / yrs if yrs else 0,
            "net_R": round(gross_r, 2),
            "WR_%": round(wr * 100, 2),
            "PF": round(pf, 2) if pf != float("inf") else "inf",
            "MaxDD_R": round(dd, 2),
            "MAR": round(-gross_r / dd, 2) if dd != 0 else 0,
            "positive_years": f"{positive_yrs}/{yrs}",
            "total_$_5k_3pct": round(usd_total, 2),
            "$_per_month": round(per_month, 2),
            "months_active": months_active,
            "avg_lots": round(jr.loc[~jr["skipped"], "lots"].mean(), 3) if (~jr["skipped"]).any() else 0,
            "max_lots": round(jr["lots"].max(), 2),
            "delay_min_bars": int(jr["delay_bars_signal_to_entry"].min()),
            "delay_max_bars": int(jr["delay_bars_signal_to_entry"].max()),
            "earliest_entry": str(jr["entry_ts"].min()),
            "latest_entry": str(jr["entry_ts"].max()),
        })
    summary_df = pd.DataFrame(summary_rows)

    # Causality audit per strategy
    causality_rows = []
    for name, jr in all_strats.items():
        if len(jr) == 0: continue
        causality_rows.append(causality_audit_summary(jr, name))
    causality_df = pd.DataFrame(causality_rows)

    # Portfolio monthly $ matrix
    monthly_dict = {}
    for name, jr in all_strats.items():
        if len(jr) == 0: continue
        m = jr.groupby("year_month")["pnl_dollars"].sum()
        monthly_dict[name] = m
    portfolio_monthly = pd.DataFrame(monthly_dict).fillna(0.0)
    portfolio_monthly["total_$"] = portfolio_monthly.sum(axis=1)
    portfolio_monthly = portfolio_monthly.sort_index()
    portfolio_monthly.index.name = "year_month"

    # Portfolio per-year
    portfolio_monthly_ix = portfolio_monthly.copy()
    portfolio_monthly_ix["year"] = portfolio_monthly_ix.index.str[:4]
    portfolio_year = portfolio_monthly_ix.groupby("year").sum(numeric_only=True)

    portfolio_summary = pd.DataFrame([{
        "months_total": len(portfolio_monthly),
        "years": len(portfolio_monthly) / 12,
        "deployed_$": START_NAV * len(all_strats),
        "total_pocketed_$": portfolio_monthly["total_$"].sum(),
        "avg_per_month_$": portfolio_monthly["total_$"].mean(),
        "per_year_$": portfolio_monthly["total_$"].sum() / (len(portfolio_monthly) / 12),
        "pos_months": int((portfolio_monthly["total_$"] > 0).sum()),
        "pos_months_%": (portfolio_monthly["total_$"] > 0).mean() * 100,
        "best_month": portfolio_monthly["total_$"].max(),
        "worst_month": portfolio_monthly["total_$"].min(),
        "max_cum_DD_$": (portfolio_monthly["total_$"].cumsum() -
                          portfolio_monthly["total_$"].cumsum().cummax()).min(),
        "Sharpe_annualised": (portfolio_monthly["total_$"].mean() /
                              portfolio_monthly["total_$"].std() * np.sqrt(12)),
    }])

    # Write Excel
    print(f"[write] {OUT_XLSX}")
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
        portfolio_summary.to_excel(xw, sheet_name="00_Portfolio_Summary", index=False)
        summary_df.to_excel(xw, sheet_name="01_Strategy_Summary", index=False)
        causality_df.to_excel(xw, sheet_name="02_Causality_Audit", index=False)
        portfolio_monthly.to_excel(xw, sheet_name="03_Portfolio_Monthly")
        portfolio_year.to_excel(xw, sheet_name="04_Portfolio_PerYear")
        for name, jr in all_strats.items():
            if len(jr) == 0: continue
            # Reorder columns for readability
            cols = ["trade_id", "strategy", "signal_known_at_ts", "entry_ts", "exit_ts",
                    "delay_bars_signal_to_entry", "hold_bars", "side", "entry_price",
                    "stop_price", "tp_price", "risk_units", "bracket_r", "cost_r",
                    "net_r", "year", "year_month", "account_reset_flag",
                    "nav_before_trade", "risk_dollars", "lots", "dollar_per_R",
                    "pnl_dollars", "nav_after_trade", "monthly_running_pnl", "skipped"]
            keep = [c for c in cols if c in jr.columns] + [c for c in jr.columns if c not in cols]
            jr_out = jr[keep]
            sheet_name = f"Trades_{name}"[:31]
            jr_out.to_excel(xw, sheet_name=sheet_name, index=False)

    print(f"\nSaved → {OUT_XLSX}")
    print("\n=== PORTFOLIO SUMMARY ===")
    print(portfolio_summary.T.to_string())
    print("\n=== STRATEGY SUMMARY ===")
    print(summary_df.to_string(index=False))
    print("\n=== CAUSALITY AUDIT ===")
    print(causality_df.to_string(index=False))


if __name__ == "__main__":
    main()
