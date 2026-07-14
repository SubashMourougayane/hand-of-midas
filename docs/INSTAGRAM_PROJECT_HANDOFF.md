# Hand of Midas — Project Handoff for Content / Social Agent

**Purpose of this document:** Give a content-creation agent everything it needs to understand this project deeply enough to write authentic Instagram content, explain the story, and generate creative ideas — without misrepresenting the facts. Read this fully before writing a single caption.

**Last updated:** 2026-07-08

---

## 1. The One-Line Pitch

**Hand of Midas** is an autonomous algorithmic trading system for gold (XAUUSD) — a fully-coded strategy that scans the market every 15 minutes, decides its own trades, sizes its own risk, executes through a broker, and reports itself in real time. It was built by one trader obsessed with a single question: *"Can we prove it actually works — or are we just telling ourselves a story?"*

It is not a "get rich" bot. It is a rigor project. The entire personality of this thing is **honesty over hype**.

---

## 2. What Actually Exists (The Real System)

This is a genuinely built, running system — not a concept. Components:

- **The Strategy ("Fib V2 Intraday")** — a Fibonacci-retracement-based gold strategy that trades two complementary "legs" (called A and D) on the 15-minute timeframe. It waits for a specific market structure (a swing pivot → a pullback into a Fibonacci zone → a confirmation candle) before entering. It is *selective* — roughly one trade per leg per day on average. Most of the time it says "no."
- **The Engine (`bt_engine`)** — the Python codebase that runs the exact same code in backtest and live. This "one code, two modes" design is a core point of pride: the historical simulation and the live trader are literally the same logic, so results are comparable.
- **The Dashboard ("Hand of Midas Trading Terminal")** — a live web cockpit (React + FastAPI) showing open trades, account equity, trade history, and a gate-by-gate breakdown of why the engine took or rejected each setup. Custom-designed, mobile-friendly, with a gold "Midas" brand mark.
- **The Live Deployment** — runs 24/5 on a Windows VPS, trading through the MetaTrader 5 platform via a file-bridge, on a **demo account** (see compliance section — this matters).
- **The Telegram Notifier (`@hand_of_midas_trade_bot`)** — pushes a formatted alert to Telegram on every trade entry, partial take-profit, and close, with the real broker P&L.

**Everything above is real and operational as of this writing.**

---

## 3. The Story (This Is Your Best Content Material)

The compelling part is not the returns. It's the **process and the philosophy**. Themes a content agent should lean into:

### Theme A: "Can we prove it?"
The founder (Subash) treated every promising result as a lie until it survived attack. There is a documented practice of running a **15-point hostile audit** on any strategy and a **"big numbers audit"** — a rule that *any* impressive number triggers a full skeptical review before it's believed. This is deeply unusual and deeply honest. Content angle: *the discipline of not fooling yourself.*

### Theme B: The Graveyard of Rejected Ideas
Dozens of strategies and "edges" were built, tested, and **killed** — not because they didn't look good, but because they didn't survive rigorous checks (out-of-sample, cross-symbol, one-bar-delay tests, look-ahead-bug hunts). There's literally an internal "Filter Research Graveyard" and a "strategy graveyard." The system that survived (Fib V2) is the rare thing that passed *every* gate. Content angle: *most ideas that look like edge are illusions — here's how we find out.*

### Theme C: Look-Ahead Bugs — the silent killer
A recurring hero-villain in this project is the **look-ahead bug**: code that accidentally peeks at future data and makes a backtest look brilliant when the real edge is near zero. Multiple were caught and documented (ORB leakage, EMA interior leaks, a +66,000R phantom edge from filling on the wrong bar). Content angle: *why 95% of "profitable" backtests on the internet are secretly cheating.*

### Theme D: Backtest vs. Live Reality ("parity")
Obsessive verification that the live trades match what the backtest would have done — down to the cent. When they *don't* match, the cause is investigated to the root (e.g., a broker revising a candle's price a second after the bot acted). Content angle: *the gap between theory and reality, and closing it honestly.*

### Theme E: The Human + AI Partnership
The project was built as a long collaboration between the trader and an AI research partner — thousands of conversations, experiments, and audits. The founder describes it as having "a teammate who never got tired of asking, 'Can we prove it?'" Content angle: *what serious human-AI collaboration actually looks like — not prompts, but a shared obsession with truth.*

---

## 4. The Numbers — HANDLE WITH CARE

⚠️ **This section is where content can go wrong. Read the guardrails.**

**Backtested performance (historical simulation, ~20 years, ~28,000 trades):**
- Win rate ≈ 48.9% (it wins less than half the time — the edge is in the *size* of wins vs losses, not frequency).
- Positive net expectancy across the full history.
- The strategy is designed with a monthly profit-skim risk model ("Model B") so it structurally never wipes the account.

**Live account (demo), current:**
- Started around $10,000; currently around $10,787.
- Trades a handful of times per day, small dollar amounts per trade.

### GUARDRAILS — non-negotiable for public content:
1. **It is a DEMO account.** Not real money (yet). Never imply real profits are being withdrawn. You can say "live paper-trading" / "live on a demo account" — that's honest and still impressive.
2. **Backtest ≠ future.** The big lifetime/compounded figures (six or seven figures over decades) are *historical simulations and projections*, NOT promises, NOT typical, NOT what a follower would get. If you ever cite them, frame them explicitly as "20-year backtest" with "past simulation is not future results."
3. **No financial advice. No signals-for-sale framing. No "follow me to get rich."** The brand's whole credibility is honesty — one hype post destroys it.
4. **Win rate is UNDER 50% — lean into that.** It's a *feature*. "We lose more often than we win, and still come out ahead" is a more honest and more interesting hook than a fake 90% win rate.
5. **Don't publish live secrets** — no broker credentials, no server IPs, no API tokens, no account login numbers. (These exist in the project but must never appear in content.)

---

## 5. Brand & Voice

- **Name:** Hand of Midas / Midas / "the Midas terminal."
- **Bot handle:** `@hand_of_midas_trade_bot` (Telegram).
- **Symbol/motif:** Gold. The Midas touch. A gold coin / gold mark. The dashboard theme is dark with gold accents.
- **Tone:** Rigorous, honest, a little obsessive, quietly confident. Anti-hype. The opposite of "forex guru" culture. Think *engineering lab notebook meets trading desk*, not *Lamborghini reel*.
- **Enemy to position against:** hype-merchant trading influencers, fake 95%-win-rate bots, signal-selling scams, survivorship-bias screenshots.
- **Core value:** *proof over promises.*

---

## 6. Content Pillar Ideas (Starter Set)

1. **"Kill Journal"** — a recurring series where you show a strategy that *looked* profitable and explain exactly how it was proven fake and killed. (Endless material, highly educational, builds trust.)
2. **"Why the bot said NO"** — screenshots of the gate-by-gate rejection funnel. The bot passes on 99% of setups. Show a day where it looked at ~66 candles and took ONE trade.
3. **"Backtest vs Reality"** — side-by-side of what the historical code would do vs what actually happened live, and the honest reason for any difference.
4. **"Look-ahead bug of the week"** — teach the single most common way backtests lie. Great educational hook.
5. **"Anatomy of a trade"** — walk through one real trade end-to-end: the pivot, the fib zone, the confirmation, entry, partial take-profit, exit, and the P&L.
6. **"Building in public"** — the dashboard, the Telegram alerts, the infrastructure. The craft of the system itself.
7. **"The rules I follow so I don't fool myself"** — the audit mandates, the discipline. Philosophy content.
8. **Human + AI build logs** — the collaboration story, how the system was actually made.

---

## 7. What to Ask Subash Before Publishing

- Which specific numbers is he comfortable showing publicly (equity? per-trade P&L? backtest headline?).
- Whether the account status changes from demo to real (this changes everything about how you talk about P&L).
- Whether the strategy internals (exact fib levels, sessions, hold caps) are public or trade-secret — **default assumption: keep the precise parameters private; talk about the *concepts*, not the exact recipe.**
- Approval on any post that cites a dollar figure.

---

## 8. Hard Facts Cheat-Sheet (for accuracy)

- **Asset traded:** Gold, XAUUSD, 15-minute timeframe.
- **Strategy family:** Fibonacci retracement, two complementary legs (A and D).
- **Style:** Intraday, selective (~1 trade/leg/day avg), holds hours not days.
- **Risk model:** Percentage-of-equity per trade with monthly profit-skim ("Model B"). Recently adjusted from 1.5% to 3% risk per trade.
- **Win rate:** ~49% (sub-50, by design).
- **Backtest span:** ~20 years, ~28,000 trades.
- **Live status:** Running 24/5, demo account, via MetaTrader 5.
- **Stack:** Python engine, React + FastAPI dashboard, PostgreSQL, Telegram bot, Windows VPS.
- **Philosophy:** Hostile auditing, look-ahead-bug hunting, backtest-live parity, honesty over hype.
- **Safety:** Guards that reject bad fills (excessive slippage), cap position size, and a risk model that structurally can't wipe out.

---

## 9. The Founder's Own Words (voice reference)

From a note left in the project:

> "This repository is more than just code. It's the result of countless experiments, failed hypotheses, late-night debugging sessions, and an obsession with finding what actually works—not what people say works."

That sentence *is* the brand. Everything you write should feel like it came from that mindset.

---

**Bottom line for the content agent:** The story here is not "a bot that prints money." It's "a person who refused to believe his own results until they survived every attack he could throw at them — and built a machine that trades on only what was left." Sell the rigor. The rigor is the product.
