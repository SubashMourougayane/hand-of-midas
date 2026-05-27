# Hand Of Midas — Project Status

**Last updated:** 2026-05-27  
**Total build time:** 5 days (May 22-27)  
**Commits:** 113  
**Status:** LIVE on Contabo VPS with JustMarkets MT5. Zero trades executed yet (3 days live).

---

## Timeline

| Date | Milestone |
|---|---|
| May 22 | Day 0: Built from scratch after phantom fill bug killed VibeTrader system. 3 Gold + 1 Oil strategy, honest fill model, 11-point audit, dashboard, EC2 deploy. |
| May 23-25 | Hardened: Oil live engine, 91 tests, Telegram notifications, EC2 CI/CD, Alpha-Sweep widened 08-20 UTC (3/day), bias filter research (8 variants). First live day — no trade (quiet market). |
| May 26-27 | Variant C deployed, JustMarkets MT5 integration built, Contabo Windows VPS ordered + deployed, engulfing tolerance (+54% P&L), full infrastructure migration, OANDA root-cause investigation (522 killed 4 trades). |

---

## Live Infrastructure

| Component | Location | Status |
|---|---|---|
| MT5 Terminal | Contabo VPS (84.247.177.145) | Running, DWX_Server streaming |
| Gold Backend (port 5053) | Contabo VPS | Running, EXECUTOR=mt5 |
| Oil Backend (port 5054) | Contabo VPS | Running, EXECUTOR=mt5 |
| Frontend (Next.js) | Contabo VPS (port 3001) | Running |
| Caddy (HTTPS) | Contabo VPS (port 443) | Windows service, auto-SSL |
| PostgreSQL 17 | Contabo VPS | Running |
| Domain | midas.subashtrades.in → 84.247.177.145 | Active, SSL certificate obtained |
| EC2 (OANDA backup) | AWS t3.small | Running but unreliable (522 errors) |
| JustMarkets Demo | Account 1100447101, Server JustMarkets-Demo2 | Connected |

**VPS Specs:** 4 vCPU, 8GB RAM, 75GB NVMe, Windows Server 2025, Hub Europe  
**Cost:** €12/month (Contabo Cloud VPS 10 + Windows license)

---

## Strategy Performance (Backtest — 21 years, $5K/yr capital)

### Production Strategies (Variant C + Tolerance)

| Strategy | Trades | WR | PF | Total $ | $/yr |
|---|---|---|---|---|---|
| Gold Alpha-Sweep | 1,341 | 67.4% | ~3.5 | +$220,000 | +$10,500 |
| Oil Alpha-Sweep | 1,606 | 66.3% | 4.71 | +$2,144,145 | +$102,000 |
| Gold Mean-Rev | 133 | 68.4% | 3.14 | +$27,000 | +$1,300 |
| Gold Cross-Market | 575 | 49.4% | 1.74 | +$41,000 | +$1,900 |

### Strategies Tested & Rejected

| Strategy | PF | Result |
|---|---|---|
| London Open Breakout | 0.66 | LOSES MONEY |
| NY Open Reversal | 0.70 | LOSES MONEY |
| Session Overlap Fade | 1.33 | Barely break-even |
| Asia Range Breakout (trend) | 0.80 | LOSES MONEY |
| Momentum Continuation | 0.74 | LOSES MONEY |
| Previous Day Breakout (trend) | 0.89 | LOSES MONEY |
| Chandelier + ZLSMA scalping | 0.67 | LOSES MONEY |
| Asia sweeps previous session | 1.98 | Weak (+$941/yr) |

**Conclusion:** Only reversal strategies work on Gold/Oil with honest fills. ALL trend-following, breakout, and momentum strategies lose money over 21 years.

---

## Key Technical Decisions

| Decision | Rationale |
|---|---|
| Variant C bias (body < 40% = neutral) | +10.3% more P&L than Variant A |
| Engulfing tolerance (Gold $0.10, Oil $0.01) | +54% more P&L, catches $0.02-0.10 near-misses |
| JustMarkets over OANDA | OANDA 522 killed 4 trades in 1 day. MT5 = zero API failures. |
| Windows VPS over Wine/EC2 | MT5 native on Windows, no Wine instability |
| DWX file bridge over MetaTrader5 package | MT5 Python package is Windows-only; DWX works cross-platform |
| Scan window 08-20 UTC only | Late night (20-24) PF 0.89 — loses money |
| Fixed SL/TP (no trailing) | Trailing SL creates phantom fills in backtest |
| Break-even at 50% TP | Reduces loss severity without phantom fill risk |
| Max hold 80 M3 bars (4hrs) | Most profitable trades resolve within 2-3 hours |

---

## Live Trading Record

| Date | Gold | Oil | Notes |
|---|---|---|---|
| May 25 (Sun) | No sweep | No sweep | Market ranged inside Asia range |
| May 26 (Mon) | Near-miss $0.02 | 3 missed (OANDA 522) | Memorial Day low vol + API failures |
| May 27 (Tue) | Sweep but bias blocks | Sweep but trending | Strong bearish day, no reversal pattern |

**Expected frequency:** ~2-3 trades/week combined (backtest average: Gold 1.2/wk + Oil 1.5/wk)  
**3 days with 0 trades is statistically normal.** The system needs a day with:
1. Decent Asia range (>$5 Gold, >$0.50 Oil)
2. Sweep of Asia high OR low during 08-20 UTC
3. H1 bar closes back inside range (reversal, not breakdown)
4. Bias allows the direction (or neutral)
5. M3 engulfing forms within 2 hours of sweep

---

## Fill Model Rules (Non-Negotiable)

```
1. Gap-through SL: fills at OPEN (worse than SL)
2. TP: fills ONLY on touch (bar HIGH >= TP for long)
3. SL: fills ONLY on touch (bar LOW <= SL for long)
4. If both hit same bar (no gap): TP wins (OANDA limit fires first)
5. Break-even: moves SL to entry+slippage at 50% TP distance
6. Slippage: 0.03 + bar_range*0.003 + random(0,0.02)
7. Max hold: exit at last bar close (no infinite holds)
```

**ZERO phantom fills in 21 years of testing (verified).**  
**Same file used by backtest AND live — `backend/execution/fill_model.py`**

---

## Test Harness

- **Total tests:** 127
- **Passing:** 107
- **Failing:** 20 (Oil import collision on Windows — fix pushed, pending VPS pull)
- **Coverage:** Fill model, bias filter, DD protection, break-even, signal execution, position monitor, parity

---

## Open Items

| Priority | Item | Status |
|---|---|---|
| HIGH | Wait for first live trade | System correct, needs right market day |
| HIGH | Install backends as NSSM services | Pending (survive VPS reboot) |
| MED | Fix remaining 20 test failures | Fix pushed, needs VPS pull + verify |
| MED | Frontend show EXPIRED instead of blinking DETECTED | Not started |
| MED | Add IST trade times to backtest table | Not started |
| LOW | Decommission EC2 | After 48hr VPS stability |
| LOW | Cross-Market missing bond data on MT5 | Find proxy or disable |
| LOW | Update backtest CSVs on VPS (ends May 24) | Need to append new bars |

---

## Access & Credentials

| System | Details |
|---|---|
| Contabo VPS | 84.247.177.145, administrator, [in email] |
| JustMarkets MT5 | 1100447101, JustMarkets-Demo2 |
| OANDA (EC2) | 101-004-39331014-001, UK demo GBP |
| Dashboard | https://midas.subashtrades.in |
| Login | subashtrades.in@gmail.com / 9994605758 |
| GitHub | SubashMourougayane/hand-of-midas |
| EC2 SSH | vibetrader-key.pem, ubuntu@midas.subashtrades.in (still on EC2 IP in ~/.ssh) |
| Telegram Bot | @hand_of_midas_trade_bot, chat 8935121886 |
