"""
Chandelier Exit (22,3) + ZLSMA (50) — XAU/USD 1-min scalping backtest.
Honest fills: entry at next bar open (ask for long, bid for short) + slippage.
No phantom fills. No look-ahead bias.

Strategy:
- ZLSMA(50) determines trend direction
- Chandelier Exit(22,3) generates Buy/Sell signals
- Buy: CE flips to buy AND price > ZLSMA → LONG
- Sell: CE flips to sell AND price < ZLSMA → SHORT
- Exit: opposite signal (always in market, or use SL)

Run: python scripts/chandelier_zlsma_backtest.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd

np.random.seed(42)

# ─── CONFIG ──────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
INSTRUMENT = "XAU_USD"

# Chandelier Exit params
CE_PERIOD = 22
CE_MULT = 3.0

# ZLSMA params
ZLSMA_LENGTH = 50

# Trade params
SPREAD = 0.50        # XAU/USD typical spread ($0.50)
SLIPPAGE = 0.10      # additional slippage per trade
CAPITAL = 5000.0
RISK_PER_TRADE = 0.02  # 2% risk
FIXED_SL = 3.0       # $3 fixed SL (tight for scalping)
FIXED_TP = 6.0       # $6 TP (2:1 R:R)
MAX_HOLD_BARS = 60   # Max 60 bars (1 hour on 1-min)


# ─── INDICATORS ──────────────────────────────────────────────────────

def calc_atr(df, period=22):
    """Average True Range."""
    high = df["mid_high"]
    low = df["mid_low"]
    close = df["mid_close"].shift(1)
    tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_chandelier_exit(df, period=22, mult=3.0):
    """
    Chandelier Exit — trailing stop based on ATR from highest high / lowest low.
    Returns: Series of 'long' or 'short' (current signal state).
    """
    atr = calc_atr(df, period)
    highest = df["mid_high"].rolling(period).max()
    lowest = df["mid_low"].rolling(period).min()

    # Long stop: highest high - mult * ATR
    long_stop = highest - mult * atr
    # Short stop: lowest low + mult * ATR
    short_stop = lowest + mult * atr

    # Determine direction
    direction = pd.Series(index=df.index, dtype="object")
    direction.iloc[0] = "long"

    for i in range(1, len(df)):
        prev_dir = direction.iloc[i - 1]
        close = df["mid_close"].iloc[i]

        if prev_dir == "long":
            if close < long_stop.iloc[i]:
                direction.iloc[i] = "short"
            else:
                direction.iloc[i] = "long"
        else:
            if close > short_stop.iloc[i]:
                direction.iloc[i] = "long"
            else:
                direction.iloc[i] = "short"

    return direction


def calc_zlsma(df, length=50):
    """
    Zero-Lag Least Squares Moving Average.
    ZLSMA = 2 * LSMA(length) - LSMA(LSMA(length))
    """
    close = df["mid_close"]

    def lsma(src, period):
        result = pd.Series(index=src.index, dtype=float)
        for i in range(period - 1, len(src)):
            window = src.iloc[i - period + 1:i + 1].values
            x = np.arange(period)
            slope = np.polyfit(x, window, 1)[0]
            result.iloc[i] = window[-1] + slope
        return result

    lsma1 = lsma(close, length)
    lsma2 = lsma(lsma1, length)
    zlsma = 2 * lsma1 - lsma2
    return zlsma


# ─── DATA LOADING ────────────────────────────────────────────────────

def load_m1_from_m3():
    """
    We don't have M1 data. Use M3 as proxy (3-min bars).
    Results will be slightly different from 1-min but same logic.
    Alternatively, aggregate from M3 to approximate M1 behavior.
    """
    print("Loading XAU_USD M3 data (using as proxy for 1-min)...")
    df = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_M3.csv"), parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.set_index("timestamp", inplace=True)

    # Compute mid prices
    df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
    df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
    df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
    df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2

    print(f"  Loaded {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
    return df


# ─── BACKTEST ENGINE ─────────────────────────────────────────────────

def run_backtest(df, start_year=2023, end_year=2025):
    """
    Run Chandelier + ZLSMA backtest with honest fills.
    Entry: NEXT bar open (ask for long, bid for short) + slippage
    Exit: fixed SL/TP or opposite signal or max hold
    """
    print(f"\nComputing indicators (CE {CE_PERIOD},{CE_MULT} + ZLSMA {ZLSMA_LENGTH})...")

    # Filter date range first to speed up
    df = df[(df.index.year >= start_year) & (df.index.year <= end_year)].copy()
    print(f"  Date range: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} bars)")

    # Compute indicators
    ce_direction = calc_chandelier_exit(df, CE_PERIOD, CE_MULT)
    zlsma = calc_zlsma(df, ZLSMA_LENGTH)

    df["ce_dir"] = ce_direction
    df["zlsma"] = zlsma

    # Detect signal flips
    df["ce_prev"] = df["ce_dir"].shift(1)
    df["ce_flip_long"] = (df["ce_dir"] == "long") & (df["ce_prev"] == "short")
    df["ce_flip_short"] = (df["ce_dir"] == "short") & (df["ce_prev"] == "long")

    # Generate signals: CE flip + ZLSMA confirmation
    df["signal"] = "none"
    df.loc[df["ce_flip_long"] & (df["mid_close"] > df["zlsma"]), "signal"] = "long"
    df.loc[df["ce_flip_short"] & (df["mid_close"] < df["zlsma"]), "signal"] = "short"

    print(f"  Signals: {(df['signal'] == 'long').sum()} longs, {(df['signal'] == 'short').sum()} shorts")

    # Execute trades with honest fills
    trades = []
    position = None  # {'side', 'entry', 'sl', 'tp', 'bar_idx', 'entry_bar'}

    for i in range(ZLSMA_LENGTH + CE_PERIOD, len(df) - 1):
        signal = df["signal"].iloc[i]

        # Check if we need to exit current position
        if position is not None:
            bars_held = i - position["entry_bar"]

            if position["side"] == "long":
                # Check SL (bar low touches SL)
                if df["bid_low"].iloc[i] <= position["sl"]:
                    exit_price = position["sl"] - SLIPPAGE * 0.5
                    pnl = exit_price - position["entry"]
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "long", "reason": "sl", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    continue
                # Check TP (bar high touches TP)
                elif df["bid_high"].iloc[i] >= position["tp"]:
                    exit_price = position["tp"]
                    pnl = exit_price - position["entry"]
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "long", "reason": "tp", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    continue
                # Max hold
                elif bars_held >= MAX_HOLD_BARS:
                    exit_price = df["bid_close"].iloc[i] - SLIPPAGE * 0.5
                    pnl = exit_price - position["entry"]
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "long", "reason": "expired", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    continue
                # Opposite signal exit
                elif signal == "short":
                    exit_price = df["bid_close"].iloc[i] - SLIPPAGE * 0.5
                    pnl = exit_price - position["entry"]
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "long", "reason": "signal_flip", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    # Fall through to open short below

            elif position["side"] == "short":
                if df["ask_high"].iloc[i] >= position["sl"]:
                    exit_price = position["sl"] + SLIPPAGE * 0.5
                    pnl = position["entry"] - exit_price
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "short", "reason": "sl", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    continue
                elif df["ask_low"].iloc[i] <= position["tp"]:
                    exit_price = position["tp"]
                    pnl = position["entry"] - exit_price
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "short", "reason": "tp", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    continue
                elif bars_held >= MAX_HOLD_BARS:
                    exit_price = df["ask_close"].iloc[i] + SLIPPAGE * 0.5
                    pnl = position["entry"] - exit_price
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "short", "reason": "expired", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None
                    continue
                elif signal == "long":
                    exit_price = df["ask_close"].iloc[i] + SLIPPAGE * 0.5
                    pnl = position["entry"] - exit_price
                    trades.append({"entry": position["entry"], "exit": exit_price, "pnl": pnl,
                                   "side": "short", "reason": "signal_flip", "bars": bars_held,
                                   "date": df.index[i]})
                    position = None

        # Open new position on signal (only if flat)
        if position is None and signal != "none":
            # Entry at NEXT bar open + spread + slippage (honest fill)
            next_bar = i + 1
            if next_bar >= len(df):
                break

            if signal == "long":
                entry_price = df["ask_open"].iloc[next_bar] + SLIPPAGE
                sl = entry_price - FIXED_SL
                tp = entry_price + FIXED_TP
                position = {"side": "long", "entry": entry_price, "sl": sl, "tp": tp, "entry_bar": next_bar}
            elif signal == "short":
                entry_price = df["bid_open"].iloc[next_bar] - SLIPPAGE
                sl = entry_price + FIXED_SL
                tp = entry_price - FIXED_TP
                position = {"side": "short", "entry": entry_price, "sl": sl, "tp": tp, "entry_bar": next_bar}

    return trades


# ─── ANALYSIS ────────────────────────────────────────────────────────

def analyze(trades):
    if not trades:
        print("  No trades!")
        return

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_pnl = sum(t["pnl"] for t in wins) if wins else 0
    loss_pnl = abs(sum(t["pnl"] for t in losses)) if losses else 1

    print(f"\n{'='*70}")
    print(f"  CHANDELIER EXIT ({CE_PERIOD},{CE_MULT}) + ZLSMA ({ZLSMA_LENGTH}) — XAU/USD M3")
    print(f"  Fixed SL: ${FIXED_SL} | TP: ${FIXED_TP} | Max Hold: {MAX_HOLD_BARS} bars")
    print(f"  Spread: ${SPREAD} | Slippage: ${SLIPPAGE}")
    print(f"{'='*70}")
    print(f"  Total Trades:   {len(trades)}")
    print(f"  Wins:           {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
    print(f"  Losses:         {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
    print(f"  Profit Factor:  {win_pnl/loss_pnl:.2f}")
    print(f"  Total P&L:      ${total_pnl:,.0f} (per unit)")
    print(f"  Avg Win:        ${np.mean([t['pnl'] for t in wins]):.2f}" if wins else "")
    print(f"  Avg Loss:       ${np.mean([t['pnl'] for t in losses]):.2f}" if losses else "")
    print(f"  Avg Bars Held:  {np.mean([t['bars'] for t in trades]):.0f}")
    print(f"  Trades/Day:     {len(trades) / ((trades[-1]['date'] - trades[0]['date']).days or 1):.1f}")

    # Exit reason breakdown
    print(f"\n  Exit Reasons:")
    for reason in ["tp", "sl", "signal_flip", "expired"]:
        count = sum(1 for t in trades if t["reason"] == reason)
        rpnl = sum(t["pnl"] for t in trades if t["reason"] == reason)
        if count > 0:
            print(f"    {reason:<12}: {count:>5} trades, P&L: ${rpnl:>+10,.0f}")

    # Monthly P&L
    print(f"\n  Monthly P&L (per unit, recent 6 months):")
    df_trades = pd.DataFrame(trades)
    df_trades["month"] = df_trades["date"].dt.to_period("M")
    monthly = df_trades.groupby("month").agg({"pnl": ["sum", "count"]}).tail(6)
    for idx, row in monthly.iterrows():
        print(f"    {idx}: {row[('pnl','count')]:.0f} trades, ${row[('pnl','sum')]:>+8,.0f}")

    # Spread impact
    total_spread_cost = len(trades) * SPREAD
    print(f"\n  Spread cost ({len(trades)} trades × ${SPREAD}): ${total_spread_cost:,.0f}")
    print(f"  P&L after spread: ${total_pnl - total_spread_cost:,.0f}")
    print(f"  Spread as % of gross P&L: {total_spread_cost/max(win_pnl,1)*100:.1f}%")
    print(f"{'='*70}")


# ─── MAIN ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = load_m1_from_m3()
    trades = run_backtest(df, start_year=2023, end_year=2025)
    analyze(trades)
