# SDR-002 Break Test — ema8 + orb_reversal + Asia/Post-Close

Generated: 2026-06-29

## Rule Under Attack

Candidate rule: `ema8_aligned == True AND orb_reversal == True AND entry_session in {asia_late, post_close}`.

Input universe: `/Users/subash/Documents/QUANT/SupplyDemand/research/l99_m15_filter_edge_sweep/m15_2c_1atr_feature_matrix.csv`.

## Headline

- 2-flag parent: 2,508 trades, +850.92R, WR 71.7%, PF 2.10, DD -12.60R, MAR 10.05, 8/8 years, 80/82 months
- 3-flag avoid-after-hours parent: 1,802 trades, +842.95R, WR 77.7%, PF 2.96, DD -7.71R, MAR 16.29, 8/8 years, 80/82 months
- Session-filtered candidate: 1,362 trades, +760.44R, WR 82.9%, PF 3.93, DD -5.20R, MAR 21.79, 8/8 years, 82/82 months

## What I Tried To Break

### 1. Session Contamination

- `asia_late`: 875 trades, +532.45R, PF 4.73, DD -5.36R, MAR 14.83
- `post_close`: 487 trades, +227.99R, PF 2.95, DD -4.03R, MAR 8.48

Result: the chosen rule is intentionally concentrated in only two sessions. That improves the stats, but it creates a live-spread/liquidity dependency. This is the main real-world attack surface.

### 2. Year-by-Year Stability

- 2019: 51 trades, +29.28R, WR 88.2%, PF 5.05, DD -3.73R
- 2020: 199 trades, +105.53R, WR 81.4%, PF 3.58, DD -3.12R
- 2021: 197 trades, +92.94R, WR 79.7%, PF 3.04, DD -3.86R
- 2022: 228 trades, +95.25R, WR 76.8%, PF 2.60, DD -5.20R
- 2023: 199 trades, +110.61R, WR 83.9%, PF 4.04, DD -3.01R
- 2024: 217 trades, +120.10R, WR 82.5%, PF 3.88, DD -3.43R
- 2025: 196 trades, +145.21R, WR 89.3%, PF 7.58, DD -2.18R
- 2026: 75 trades, +61.52R, WR 92.0%, PF 11.12, DD -1.03R

Result: no single year carries the edge. 2025/2026 are strong, but 2019-2024 are already positive.

### 3. Monthly Weakness

Positive months: 82/82.
Worst months:
- 2020-03: 11 trades, +0.38R, PF 1.07
- 2021-08: 14 trades, +2.11R, PF 1.36
- 2019-09: 3 trades, +2.69R, PF inf
- 2022-05: 19 trades, +3.01R, PF 1.39
- 2022-06: 20 trades, +3.27R, PF 1.41
- 2024-03: 15 trades, +3.44R, PF 1.62
- 2024-11: 8 trades, +3.62R, PF 2.72
- 2021-04: 11 trades, +3.68R, PF 2.09
- 2023-06: 10 trades, +4.56R, PF 3.03
- 2025-11: 9 trades, +4.79R, PF 3.33

### 4. Cost/Slippage Stress

- extra `0.000R` per trade: +760.44R, PF 3.93, DD -5.20R, positive years 8/8
- extra `0.050R` per trade: +692.34R, PF 3.55, DD -5.60R, positive years 8/8
- extra `0.100R` per trade: +624.24R, PF 3.21, DD -6.00R, positive years 8/8
- extra `0.200R` per trade: +488.04R, PF 2.59, DD -7.46R, positive years 8/8
- extra `0.300R` per trade: +351.84R, PF 2.07, DD -9.06R, positive years 8/8
- extra `0.400R` per trade: +215.64R, PF 1.61, DD -15.39R, positive years 8/8
- extra `0.500R` per trade: +79.44R, PF 1.21, DD -30.70R, positive years 6/8
- extra `0.750R` per trade: -261.06R, PF 0.40, DD -271.44R, positive years 1/8
- extra `1.000R` per trade: -601.56R, PF 0.00, DD -601.56R, positive years 0/8

Modeled-cost multiplier stress:
- cost x1: +760.44R, PF 3.93, DD -5.20R
- cost x2: +624.87R, PF 3.19, DD -6.52R
- cost x3: +489.31R, PF 2.56, DD -8.77R
- cost x4: +353.75R, PF 2.02, DD -11.80R
- cost x5: +218.19R, PF 1.57, DD -29.85R
- cost x7.5: -120.72R, PF 0.77, DD -269.69R
- cost x10: -459.63R, PF 0.37, DD -577.58R

Result: fixed extra cost is the fastest way to kill the pretty numbers. The edge survives normal extra costs but becomes ordinary once we punish it by roughly +0.40R to +0.50R/trade. For Asia/post-close, this must be validated using live spread logs.

### 5. Top-Winner Dependency

- remove top 0: 1,362 trades, +760.44R, PF 3.93, DD -5.20R
- remove top 50: 1,312 trades, +711.11R, PF 3.74, DD -5.20R
- remove top 100: 1,262 trades, +662.19R, PF 3.55, DD -5.20R
- remove top 200: 1,162 trades, +565.62R, PF 3.18, DD -7.39R
- remove top 300: 1,062 trades, +470.61R, PF 2.81, DD -9.29R
- remove top 400: 962 trades, +376.90R, PF 2.45, DD -17.43R

Result: not one-trade dependent. Removing top 200 winners still leaves a large positive system, but removing the top 300-400 shows the payoff distribution is still meaningfully winner-supported.

### 6. Trade Clustering / Overtrading

- `first_1_per_day`: 925 trades, +485.60R, PF 3.51, DD -4.88R, MAR 14.82
- `first_2_per_day`: 1,264 trades, +697.84R, PF 3.85, DD -5.20R, MAR 20.00
- `first_3_per_day`: 1,349 trades, +752.82R, PF 3.93, DD -5.20R, MAR 21.57
- `cooldown_4h`: 1,033 trades, +550.32R, PF 3.59, DD -4.88R, MAR 16.79
- `cooldown_12h`: 925 trades, +485.60R, PF 3.51, DD -4.88R, MAR 14.82
- `cooldown_24h`: 791 trades, +433.04R, PF 3.78, DD -4.27R, MAR 15.10

Result: the edge does not disappear if we thin clustered trades. That is good. But most of the money comes from allowing multiple valid events per day, so live risk controls must cap concurrent exposure.

### 7. Direction Split

- `demand`: 726 trades, +405.54R, WR 82.9%, PF 3.95, DD -4.30R
- `supply`: 636 trades, +354.90R, WR 82.9%, PF 3.91, DD -4.05R

Result: both demand and supply contribute. This is better than the old long-only concern.

### 8. Rolling Windows

- 3m rolling: min +13.86R, median +28.38R, max +42.00R, negative windows 0/80
- 6m rolling: min +36.09R, median +55.62R, max +76.52R, negative windows 0/77
- 12m rolling: min +89.37R, median +109.65R, max +146.18R, negative windows 0/71
- 24m rolling: min +183.54R, median +213.02R, max +272.53R, negative windows 0/59

### 9. Random Same-Session Benchmark

Random benchmark sampled 1,362 trades from the same `['asia_late', 'post_close']` sessions, 2,000 times.
- Rule net: +760.44R
- Random p50 net: -116.58R
- Random p95 net: -64.15R
- Random p99 net: -42.54R
- Random max PF p99: 0.94

Result: random same-session selection does not explain the edge.

### 10. Train-Only Rule Selection

This is the meta-overfit check: I added `asia_post_session` as a boolean candidate and swept 1/2/3-flag rules using only trades before `2022-01-01`. Then I checked the fixed rules after `2022-01-01`.

Candidate train rank by net: #10. Candidate train rank by MAR: #7. Candidate train: 447 trades, +227.75R, PF 3.43, DD -3.86R, MAR 26.26. OOS: 915 trades, +532.69R, PF 4.21, DD -5.20R, MAR 23.02.

Top train-selected rules by train net:
- `orb_reversal + asia_post_session`: train +297.89R PF 2.66 MAR 30.30; OOS +608.15R PF 2.71 MAR 19.40
- `orb_reversal + avoid_after_hours + asia_post_session`: train +297.89R PF 2.66 MAR 30.30; OOS +608.15R PF 2.71 MAR 19.40
- `intraday_stack_7d + orb_reversal + asia_post_session`: train +275.86R PF 2.64 MAR 28.06; OOS +570.78R PF 2.71 MAR 18.21
- `orb_reversal + recent_fvg_20 + asia_post_session`: train +272.80R PF 2.68 MAR 24.77; OOS +538.54R PF 2.69 MAR 15.86
- `orb_reversal + zone_fvg_overlap_100 + asia_post_session`: train +270.76R PF 2.75 MAR 27.54; OOS +572.52R PF 2.97 MAR 17.26

Result: the exact session-filtered candidate is not only a full-period discovery; it is already strong in the pre-2022 training window and improves out of sample. That does not eliminate selection bias, but it materially weakens the “only picked because 2025/2026 were visible” attack.

## 5k Monthly Reset PnL

- Risk 1%: total PnL $39,841.51, positive months 82/82, worst month $16.15, best month $945.17, worst intramonth DD $-275.60
- Risk 2%: total PnL $83,554.30, positive months 82/82, worst month $26.80, best month $2,054.23, worst intramonth DD $-583.58
- Risk 3%: total PnL $131,510.62, positive months 82/82, worst month $31.90, best month $3,352.95, worst intramonth DD $-925.78
- Risk 4%: total PnL $184,117.17, positive months 82/82, worst month $31.41, best month $4,870.68, worst intramonth DD $-1,304.04
- Risk 5%: total PnL $241,818.10, positive months 82/82, worst month $25.33, best month $6,640.85, worst intramonth DD $-1,720.19

## Verdict

I could not break the candidate statistically with the usual cuts. It stays positive by year, month, direction, rolling windows, clustered-trade thinning, top-winner removal, and random same-session controls.

The thing that can still break it is not a spreadsheet slice. It is live execution: Asia/post-close spreads, slippage, broker stop behavior, and whether `orb_reversal` is computed causally and identically in the live engine.

Promotion condition I would require before calling this live-base SDR-002:

1. Run a live spread sampler for the exact sessions for at least one week.
2. Confirm the live engine reproduces the historical feature flags bar-by-bar for `ema8_aligned`, `orb_reversal`, and session classification.
3. Paper-live at 0.01 lot for 20-30 real trades, with every fill audited against expected entry/SL/TP.
4. If realized cost stays below +0.20R/trade equivalent, this candidate deserves promotion over SDR-001.