![header](https://capsule-render.vercel.app/api?type=waving&height=220&text=Hand%20Of%20Midas&fontAlign=50&fontAlignY=38&color=0:0a0d12,50:1a1f2b,100:0e1117&fontColor=e8c300&fontSize=55&animation=fadeIn&desc=Everything%20It%20Touches%20Turns%20To%20Gold&descAlign=50&descAlignY=60&descSize=18&descColor=9ca3b4)

<div align="center">

[![Typing SVG](https://readme-typing-svg.demolab.com/?lines=Session+Sweep+%7C+Mean+Reversion+%7C+Inter-Market;20+Years+Backtested+%7C+Zero+Losing+Years;Gold+%2B+Oil+%7C+PF+3.40+%26+8.31;Built+After+Discovering+89%25+Phantom+Fill+Bug;Every+Number+Is+Honest&font=JetBrains+Mono&center=true&width=550&height=45&color=00e87b&vCenter=true&pause=1000&size=15)](https://git.io/typing-svg)

<br/>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![OANDA](https://img.shields.io/badge/OANDA-Live-2E7D32?style=for-the-badge)
![Tailwind](https://img.shields.io/badge/Tailwind-v4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)

<br/><br/>

<table>
<tr>
<td align="center" width="50%">

**⛏️ GOLDDIGGER**
<br/>
`XAU/USD` `Gold` `3 Strategies`
<br/><br/>
Alpha-Sweep (Session Sweep)<br/>
Mean-Rev (Daily Dip-Buy)<br/>
Cross-Market (6-Instrument Consensus)<br/>
Live on OANDA Demo

</td>
<td align="center" width="50%">

**🛢️ OILMINER**
<br/>
`BCO/USD` `Brent Crude` `1 Strategy`
<br/><br/>
Alpha-Sweep (Session Sweep)<br/>
Same Logic, Oil Thresholds<br/>
72.3% Win Rate, PF 8.31<br/>
Live on OANDA Demo

</td>
</tr>
</table>

</div>

---

## Performance

<table>
<tr>
<td width="50%">

### 🥇 Gold — 20 Years (2006–2026)

```
 $5,000/yr → $177,235 total

 Profit Factor    3.40
 Win Rate         59.7%
 Trades           1,012 (49/year)
 R:R              1:2.30
 Max Drawdown     -19.0%
 Losing Years     0 / 21
```

</td>
<td width="50%">

### 🛢️ Oil — 20 Years (2006–2026)

```
 $5,000/yr → $314,803 total

 Profit Factor    8.31
 Win Rate         72.3%
 Trades           390 (19/year)
 R:R              1:3.18
 Max Drawdown     -14.9%
 Losing Years     0 / 21
```

</td>
</tr>
</table>

> **Capital Model:** Each year starts with $5,000 fresh. Profits compound within year, then withdraw. Shows repeatable annual edge without multi-year compounding illusion.

<details>
<summary><strong>Gold Strategy Breakdown</strong></summary>
<br/>

| Strategy | Trades | WR | PF | P&L | Avg Hold |
|----------|--------|-----|-----|-----|----------|
| Alpha-Sweep | 314 | 73.2% | 6.29 | $127,031 | 3.0 hrs |
| Mean-Rev | 134 | 69.4% | 3.20 | $20,984 | 3.4 days |
| Cross-Market | 564 | 49.8% | 1.72 | $29,220 | 12.8 days |

</details>

<details>
<summary><strong>Combined Portfolio (Gold + Oil)</strong></summary>
<br/>

| Metric | Value |
|--------|-------|
| **Total P&L (20yr)** | **$492,038** (₹4,76,39,519) |
| Total Trades | 1,402 |
| Trades/year | 68 |
| Strategies | 4 |
| Instruments | 2 |
| Capital deployed | $10,000/year ($5k × 2) |

</details>

---

## Strategies

<table>
<tr>
<td width="33%">

### Alpha-Sweep
`Gold + Oil` `Intraday`

```python
# SETUP
Asia session high/low (00-08 UTC)
London sweeps Asia H/L by $2+
Closes back inside = trap

# ENTRY
Wait for M3 engulfing candle
Skip first bar (spread spike)
Daily bias filter (bull/bear)

# EXIT
SL: sweep wick ± buffer
TP: 2× Asia range
BE: move SL to entry at 50%
Max: 80 bars (~4 hours)
```

</td>
<td width="33%">

### Mean-Rev
`Gold only` `Swing`

```python
# SETUP
MA10_Low dips below threshold
Close drops below MA10_High
Both conditions = oversold

# ENTRY
LONG at next day open

# EXIT
Conditions reverse
OR max 5 days
OR SL hit (1× 10d range)
Long only
```

</td>
<td width="33%">

### Cross-Market
`Gold only` `Position`

```python
# SETUP
6 markets: EUR, US10Y, SPX,
           Silver, Oil, US2Y
3-day returns → consensus

# ENTRY
Consensus ≥ 0.3 → LONG gold
Gold above 50-MA required

# EXIT
SL: 2× ATR(14)
TP: 4× ATR(14)
Max: 20 days
Long only
```

</td>
</tr>
</table>

---

## Architecture

```mermaid
graph TB
    subgraph Frontend["🖥️ Dashboard (port 3001)"]
        UI["Next.js 16 + React 19<br/>Tailwind v4 + Recharts"]
    end

    subgraph Gold["🥇 Gold Engine (port 5053)"]
        direction TB
        GS["Alpha-Sweep + Mean-Rev + Cross-Market"]
        GP["Position Monitor + Price Stream"]
    end

    subgraph Oil["🛢️ Oil Engine (port 5054)"]
        direction TB
        OS["Alpha-Sweep"]
        OP["Position Monitor + Price Stream"]
    end

    subgraph External
        OANDA["OANDA v20<br/>REST + Streaming"]
        DB[("PostgreSQL<br/>golddigger")]
    end

    UI --> Gold
    UI --> Oil
    Gold --> OANDA
    Oil --> OANDA
    Gold --> DB
    Oil --> DB
```

---

## Quick Start

```bash
# Prerequisites: PostgreSQL, Python 3.12+, Node.js 18+

# Database
createdb golddigger
psql -U subash -d golddigger -f database/schema.sql

# Launch everything
bash start.sh
```

Opens:
| Service | URL | Instrument |
|---------|-----|-----------|
| 🥇 Gold Backend | http://localhost:5053 | XAU/USD |
| 🛢️ Oil Backend | http://localhost:5054 | BCO/USD |
| 🖥️ Dashboard | http://localhost:3001 | Both |

---

## Risk Management

<table>
<tr>
<td width="50%">

**Position Sizing (Tiered)**

| Strategy | Risk % | Rationale |
|----------|--------|-----------|
| Alpha-Sweep | 4% | Best edge, reward it |
| Mean-Rev | 3% | Solid, keep steady |
| Cross-Market | 2% | Most frequent, dampen DD |

</td>
<td width="50%">

**Drawdown Protection**

| Trigger | Action |
|---------|--------|
| 3 consecutive losses | Halve position size |
| 5 consecutive losses | Pause next 2 signals |
| Equity < 20-trade MA | Halve again |
| Gold < 50-day MA | Skip Mean-Rev + Cross longs |

</td>
</tr>
</table>

---

## Safety Features

| Feature | What it prevents |
|---------|-----------------|
| ❌ No trailing stops | Phantom fills (previous system's fatal bug) |
| 🔒 Fixed SL/TP on every order | Trades always have defined risk |
| 🗄️ DB guards per strategy | Duplicate positions impossible |
| ⏱️ Max hold hard kill (80 bars) | Trades hanging open forever |
| 💱 GBP→USD live conversion | Wrong position sizing |
| 📉 DD protection (shared) | Ruin from consecutive losses |
| 📡 Real-time price stream | Missed break-even triggers |
| 🔍 11-point parity audit | Every backtest≠live issue found and fixed |

---

## Origin Story

> *"Spent 3 weeks building a system based entirely on phantom fill results. 89% of reported P&L was fake."*

This project exists because the previous trading system (VibeTrader) had a critical bug: the trailing stop-loss filled at prices the market never reached. After discovering this, we:

1. Tested **55 strategy configurations** — most lost money
2. Found **3 winners** that work with honest fills (session sweep, dip-buy, inter-market)
3. Built GoldDigger from scratch with **zero trailing stops, fixed exits only**
4. Ran an **11-point audit** comparing backtest vs live logic — fixed every discrepancy
5. Added Oil after discovering the same session-sweep edge works on Brent Crude

Every number shown is achievable in live. No phantom fills, no fake data, no shortcuts.

---

<details>
<summary><strong>Tech Stack Detail</strong></summary>
<br/>

<div align="center">

| | Technology | Role |
|---|---|---|
| <img src="https://cdn.simpleicons.org/python/3776AB" width="20"/> | **Python 3.12** | Backend engines |
| <img src="https://cdn.simpleicons.org/fastapi/009688" width="20"/> | **FastAPI** | API servers (×2) |
| <img src="https://cdn.simpleicons.org/nextdotjs/ffffff" width="20"/> | **Next.js 16** | Dashboard UI |
| <img src="https://cdn.simpleicons.org/react/61DAFB" width="20"/> | **React 19** | Frontend framework |
| <img src="https://cdn.simpleicons.org/tailwindcss/06B6D4" width="20"/> | **Tailwind v4** | Dark terminal theme |
| <img src="https://cdn.simpleicons.org/postgresql/4169E1" width="20"/> | **PostgreSQL** | Trade persistence |
| <img src="https://cdn.simpleicons.org/pandas/150458" width="20"/> | **pandas + NumPy** | Data processing |

</div>

</details>

---

<div align="center">

**Hand Of Midas — Built after failure. Validated on 20 years of data. Running live.**

<sub>Gold: 3 strategies, 49 trades/year, $177k over 20 years on $5k/year fresh capital</sub>
<br/>
<sub>Oil: 1 strategy, 19 trades/year, $315k over 20 years on $5k/year fresh capital</sub>
<br/>
<sub>Combined: $492k total, zero losing years, honest fills only</sub>

<br/><br/>

![Private](https://img.shields.io/badge/License-Private-red?style=for-the-badge)

</div>

![footer](https://capsule-render.vercel.app/api?type=waving&color=0:0a0d12,50:1a1f2b,100:0e1117&height=100&section=footer)
