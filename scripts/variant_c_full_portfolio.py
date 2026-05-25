"""Full portfolio backtest with Variant C bias filter (strong body only)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd
from datetime import timedelta
np.random.seed(42)

from backend.execution.fill_model import execute_trade
from backend.config import slippage, ALPHA_SWEEP

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")

# Load data
h1_gold = pd.read_csv(f'{DATA_DIR}/XAU_USD_H1.csv', parse_dates=['timestamp']).sort_values('timestamp').reset_index(drop=True)
m3_gold = pd.read_csv(f'{DATA_DIR}/XAU_USD_M3.csv', parse_dates=['timestamp']).sort_values('timestamp').set_index('timestamp')
daily_gold = pd.read_csv(f'{DATA_DIR}/XAU_USD_D.csv', parse_dates=['timestamp']).sort_values('timestamp').reset_index(drop=True)

h1_oil = pd.read_csv(f'{DATA_DIR}/BCO_USD_H1.csv')
h1_oil['timestamp'] = pd.to_datetime(h1_oil['timestamp'], format='mixed', utc=True)
h1_oil = h1_oil.sort_values('timestamp').reset_index(drop=True)
m3_oil = pd.read_csv(f'{DATA_DIR}/BCO_USD_M3.csv')
m3_oil['timestamp'] = pd.to_datetime(m3_oil['timestamp'], format='mixed', utc=True)
m3_oil = m3_oil.sort_values('timestamp').drop_duplicates(subset='timestamp').set_index('timestamp')
daily_oil = pd.read_csv(f'{DATA_DIR}/BCO_USD_D.csv')
daily_oil['timestamp'] = pd.to_datetime(daily_oil['timestamp'], format='mixed', utc=True)
daily_oil = daily_oil.sort_values('timestamp').reset_index(drop=True)

print(f'Gold: H1={len(h1_gold)}, M3={len(m3_gold)}, Daily={len(daily_gold)}')
print(f'Oil: H1={len(h1_oil)}, M3={len(m3_oil)}, Daily={len(daily_oil)}')

# Precompute daily metrics
for df in [daily_gold]:
    df['mid_close'] = (df['bid_close'] + df['ask_close']) / 2
    df['mid_open'] = (df['bid_open'] + df['ask_open']) / 2
    df['mid_high'] = (df['bid_high'] + df['ask_high']) / 2
    df['mid_low'] = (df['bid_low'] + df['ask_low']) / 2
    df['body'] = df['mid_close'] - df['mid_open']
    df['body_pct'] = abs(df['body']) / ((df['mid_high'] - df['mid_low']).replace(0, 1))
    df['date'] = df['timestamp'].dt.date

if 'bid_close' in daily_oil.columns:
    daily_oil['mid_close'] = (daily_oil['bid_close'] + daily_oil['ask_close']) / 2
    daily_oil['mid_open'] = (daily_oil['bid_open'] + daily_oil['ask_open']) / 2
    daily_oil['mid_high'] = (daily_oil['bid_high'] + daily_oil['ask_high']) / 2
    daily_oil['mid_low'] = (daily_oil['bid_low'] + daily_oil['ask_low']) / 2
else:
    daily_oil['mid_close'] = daily_oil['close']
    daily_oil['mid_open'] = daily_oil['open']
    daily_oil['mid_high'] = daily_oil['high']
    daily_oil['mid_low'] = daily_oil['low']
daily_oil['body'] = daily_oil['mid_close'] - daily_oil['mid_open']
daily_oil['body_pct'] = abs(daily_oil['body']) / ((daily_oil['mid_high'] - daily_oil['mid_low']).replace(0, 1))
daily_oil['date'] = daily_oil['timestamp'].dt.date


def get_bias_c(daily_df, trade_date):
    idx = daily_df[daily_df['date'] < trade_date]
    if len(idx) == 0:
        return 'neutral'
    prev = idx.iloc[-1]
    if prev['body_pct'] < 0.4:
        return 'neutral'
    return 'bullish' if prev['body'] > 0 else 'bearish'


def find_alpha_signals(h1, m3_df, daily_df, instrument='gold'):
    cfg_ext = 2.0 if instrument == 'gold' else 0.20
    cfg_sl_buf = 0.30 if instrument == 'gold' else 0.03
    cfg_min_sl = 5.0 if instrument == 'gold' else 0.10
    cfg_min_range = 5.0 if instrument == 'gold' else 0.50
    cfg_risk_floor = 0.30 if instrument == 'gold' else 0.01
    max_units = 100 if instrument == 'gold' else 5000

    sigs = []
    for trade_date in sorted(h1['timestamp'].dt.date.unique()):
        asia = h1[(h1['timestamp'].dt.date == trade_date) & (h1['timestamp'].dt.hour < 8)]
        if len(asia) < 3:
            continue
        ah = ((asia['bid_high'] + asia['ask_high']) / 2).max()
        al = ((asia['bid_low'] + asia['ask_low']) / 2).min()
        ar = ah - al
        if ar < cfg_min_range:
            continue

        scan = h1[(h1['timestamp'].dt.date == trade_date) & (h1['timestamp'].dt.hour >= 8) & (h1['timestamp'].dt.hour < 20)]
        if len(scan) == 0:
            continue

        bias = get_bias_c(daily_df, trade_date)

        sweeps = []
        for _, bar in scan.iterrows():
            mh = (bar['bid_high'] + bar['ask_high']) / 2
            ml = (bar['bid_low'] + bar['ask_low']) / 2
            mc = (bar['bid_close'] + bar['ask_close']) / 2
            if mh > ah + cfg_ext and mc < ah:
                sweeps.append(('bearish', mh, bar['timestamp']))
            elif ml < al - cfg_ext and mc > al:
                sweeps.append(('bullish', ml, bar['timestamp']))

        day_trades = 0
        for sd, sw, st in sweeps:
            if day_trades >= 3:
                break
            if bias != 'neutral':
                if sd == 'bullish' and bias != 'bullish':
                    continue
                if sd == 'bearish' and bias != 'bearish':
                    continue

            wend = st + timedelta(hours=2)
            mw = m3_df[(m3_df.index > st) & (m3_df.index <= wend)]
            if len(mw) < 3:
                continue

            for j in range(2, len(mw)):
                c = mw.iloc[j]
                pv = mw.iloc[j - 1]
                co = (c['bid_open'] + c['ask_open']) / 2
                cc = (c['bid_close'] + c['ask_close']) / 2
                po = (pv['bid_open'] + pv['ask_open']) / 2
                pc = (pv['bid_close'] + pv['ask_close']) / 2
                ct, cb = max(co, cc), min(co, cc)
                pt, pb = max(po, pc), min(po, pc)
                if sd == 'bullish' and not (cc > co and cb <= pb and ct >= pt):
                    continue
                if sd == 'bearish' and not (cc < co and cb <= pb and ct >= pt):
                    continue
                br = (c['bid_high'] + c['ask_high']) / 2 - (c['bid_low'] + c['ask_low']) / 2
                if sd == 'bullish':
                    e = c['ask_close'] + slippage(br)
                    sl = sw - cfg_sl_buf
                    r = e - sl
                    if r < cfg_min_sl:
                        sl = e - cfg_min_sl
                        r = cfg_min_sl
                    if r < cfg_risk_floor or r > ar * 0.8:
                        continue
                    tp = e + ar * 2.0
                    if tp - e < r * 0.8:
                        continue
                    sigs.append((mw.index[j], 'long', e, sl, tp, r, max_units))
                else:
                    e = c['bid_close'] - slippage(br)
                    sl = sw + cfg_sl_buf
                    r = sl - e
                    if r < cfg_min_sl:
                        sl = e + cfg_min_sl
                        r = cfg_min_sl
                    if r < cfg_risk_floor or r > ar * 0.8:
                        continue
                    tp = e - ar * 2.0
                    if e - tp < r * 0.8:
                        continue
                    sigs.append((mw.index[j], 'short', e, sl, tp, r, max_units))
                day_trades += 1
                break
    return sigs


def run_backtest(sigs, m3_df, risk_pct=4.0):
    yearly = {}
    trades = 0
    wins = 0
    total_pnl = 0
    peak = 5000
    eq = 5000
    max_dd = 0
    for (dt, d, e, s, tp, r, mu) in sigs:
        try:
            loc = m3_df.index.get_loc(dt)
            idx = loc if isinstance(loc, int) else loc.start if hasattr(loc, 'start') else int(np.where(m3_df.index == dt)[0][0])
        except:
            continue
        u = min((5000 * risk_pct / 100) / r, mu)
        res = execute_trade(df=m3_df, bar_start=idx, entry=e, sl=s, tp=tp, direction=d, max_bars=80, strategy='alpha_sweep', use_break_even=True)
        if res is None:
            continue
        p = res.pnl_per_unit * u
        trades += 1
        total_pnl += p
        if p > 0:
            wins += 1
        eq += p
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        yr = dt.year
        yearly[yr] = yearly.get(yr, 0) + p
    lose = sum(1 for v in yearly.values() if v < 0)
    yrs = len(yearly)
    wr = wins / trades if trades else 0
    return trades, wr, total_pnl, total_pnl / yrs if yrs else 0, max_dd, lose, yrs, yearly


# Run Gold Alpha-Sweep (Variant C)
print('\nRunning Gold Alpha-Sweep (Variant C)...')
np.random.seed(42)
gold_sigs = find_alpha_signals(h1_gold, m3_gold, daily_gold, 'gold')
g_t, g_wr, g_pnl, g_py, g_dd, g_ly, g_yrs, g_yearly = run_backtest(gold_sigs, m3_gold, 4.0)
print(f'  Gold Alpha: {g_t} trades, {g_wr:.1%} WR, ${g_pnl:,.0f}, DD {g_dd:.1%}')

# Run Oil Alpha-Sweep (Variant C)
print('Running Oil Alpha-Sweep (Variant C)...')
np.random.seed(42)
oil_sigs = find_alpha_signals(h1_oil, m3_oil, daily_oil, 'oil')
o_t, o_wr, o_pnl, o_py, o_dd, o_ly, o_yrs, o_yearly = run_backtest(oil_sigs, m3_oil, 4.0)
print(f'  Oil Alpha: {o_t} trades, {o_wr:.1%} WR, ${o_pnl:,.0f}, DD {o_dd:.1%}')

# Gold Mean-Rev + Cross-Market (from full engine — unchanged)
print('Running Gold full portfolio (for MR + CM numbers)...')
np.random.seed(42)
from backend.backtest.engine import run_backtest as full_backtest
full_result = full_backtest()
mr_pnl = sum(t.pnl_sized for t in full_result.trades if t.strategy == 'mean_rev')
cm_pnl = sum(t.pnl_sized for t in full_result.trades if t.strategy == 'cross_market')
mr_trades = sum(1 for t in full_result.trades if t.strategy == 'mean_rev')
cm_trades = sum(1 for t in full_result.trades if t.strategy == 'cross_market')
mr_wins = sum(1 for t in full_result.trades if t.strategy == 'mean_rev' and t.pnl_sized > 0)
cm_wins = sum(1 for t in full_result.trades if t.strategy == 'cross_market' and t.pnl_sized > 0)
mr_yearly = {}
cm_yearly = {}
for t in full_result.trades:
    if t.strategy == 'mean_rev':
        mr_yearly[t.year] = mr_yearly.get(t.year, 0) + t.pnl_sized
    elif t.strategy == 'cross_market':
        cm_yearly[t.year] = cm_yearly.get(t.year, 0) + t.pnl_sized

total_pnl = g_pnl + o_pnl + mr_pnl + cm_pnl
total_trades = g_t + o_t + mr_trades + cm_trades

print(f'\n{"="*80}')
print(f'{"FULL PORTFOLIO — VARIANT C BIAS FILTER":^80}')
print(f'{"="*80}')
print(f'{"Strategy":<30} {"Trades":>7} {"WR":>7} {"$/yr":>9} {"Total":>11} {"DD":>7}')
print(f'{"-"*80}')
print(f'{"Gold Alpha-Sweep (C)":<30} {g_t:>7} {g_wr:>6.1%} {g_py:>+9,.0f} {g_pnl:>+11,.0f} {g_dd:>6.1%}')
print(f'{"Oil Alpha-Sweep (C)":<30} {o_t:>7} {o_wr:>6.1%} {o_py:>+9,.0f} {o_pnl:>+11,.0f} {o_dd:>6.1%}')
print(f'{"Gold Mean-Rev":<30} {mr_trades:>7} {mr_wins/mr_trades if mr_trades else 0:>6.1%} {mr_pnl/g_yrs:>+9,.0f} {mr_pnl:>+11,.0f} {"":>7}')
print(f'{"Gold Cross-Market":<30} {cm_trades:>7} {cm_wins/cm_trades if cm_trades else 0:>6.1%} {cm_pnl/g_yrs:>+9,.0f} {cm_pnl:>+11,.0f} {"":>7}')
print(f'{"-"*80}')
print(f'{"TOTAL PORTFOLIO":<30} {total_trades:>7} {"":>7} {total_pnl/g_yrs:>+9,.0f} {total_pnl:>+11,.0f}')
print(f'{"="*80}')

# Year by year
print(f'\n{"Year":<6} {"Gold-A":>10} {"Oil-A":>10} {"MR":>10} {"CM":>10} {"Combined":>12}')
print(f'{"-"*65}')
all_years = sorted(set(list(g_yearly.keys()) + list(o_yearly.keys()) + list(mr_yearly.keys()) + list(cm_yearly.keys())))
lose_count = 0
for yr in all_years:
    ga = g_yearly.get(yr, 0)
    oa = o_yearly.get(yr, 0)
    mr = mr_yearly.get(yr, 0)
    cm = cm_yearly.get(yr, 0)
    combined = ga + oa + mr + cm
    if combined < 0:
        lose_count += 1
    print(f'{yr:<6} {ga:>+10,.0f} {oa:>+10,.0f} {mr:>+10,.0f} {cm:>+10,.0f} {combined:>+12,.0f}')
print(f'{"-"*65}')
print(f'{"TOTAL":<6} {g_pnl:>+10,.0f} {o_pnl:>+10,.0f} {mr_pnl:>+10,.0f} {cm_pnl:>+10,.0f} {total_pnl:>+12,.0f}')
print(f'\nLosing years: {lose_count}/{len(all_years)}')
print(f'Avg P&L/year: ${total_pnl/len(all_years):,.0f}')
print(f'Starting capital: $10,000/year ($5K per instrument)')

print(f'\n{"="*60}')
print(f'COMPARISON vs CURRENT (Variant A):')
print(f'  Current total:   $640,391')
print(f'  Variant C total: ${total_pnl:,.0f}')
print(f'  Delta:           ${total_pnl - 640391:+,.0f}')
print(f'{"="*60}')
