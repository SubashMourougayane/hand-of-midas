#!/usr/bin/env python3
"""GFT 2-Step GOAT prop simulation for A+D (log-heavy, auditable big-number test).

Rules (2-Step GOAT, from GFT FAQ 2026-07): P1 +8%, P2 +6%, daily DD 4% of day-start,
max DD 10% STATIC (equity never < 90% of start), >=3 valid days (>=0.5% each), no time
limit, funded split 80% (100% with add-on).

Method: Monte-Carlo challenge attempts on the REAL 20yr A+D strict trade stream. Each
attempt starts at a random point, plays forward FIXED-FRACTIONAL (risk = R * current
equity), and checks the gates per trade. Reports P(pass P1), P(pass P2), combined, days,
and funded monthly return -> $ payout.

HONEST LIMITATION (logged): daily-DD + max-DD are checked on CLOSE-based per-trade equity
(M15 close). Real INTRADAY excursions (open-trade MAE) are worse, so the true breach rate
is HIGHER and pass-rate LOWER than this optimistic estimate. Treat results as an UPPER bound.
"""
import sys, uuid, functools
from datetime import datetime, timezone
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to

SYM = "XAUUSD.ecn"
LOG = open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/GFT_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log", "w")
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s+"\n"); LOG.flush()

START = 5000.0
P1 = 1.08 * START      # +8%
P2 = 1.06 * START      # +6% (fresh start)
DAILY_DD = 0.04        # of day-start
MAXDD_FLOOR = 0.90 * START  # static: never below 90% of start ($4500)
VALID_DAY = 0.005 * START   # $25
MIN_VALID_DAYS = 3
MAX_TRADES_WINDOW = 1500     # ~ up to a year of A+D trades before giving up

def capture(Cls, frame, hold):
    prov = MemoryBarProvider(frame, symbol=SYM, timeframe="M15"); clk = MemoryClock(prov)
    strat = Cls(symbol=SYM); rows = {}
    def _o(tr): rows[tr.trade_id] = {"entry_ts": pd.Timestamp(tr.entry_timestamp)}
    def _c(tr, oc):
        if tr.trade_id in rows:
            cr = float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["net_r"] = oc.bracket_1r_outcome - cr
    deps = EngineDeps(clock=clk, data_provider=prov, strategy=strat, execution=BTExecutionModel(),
                      broker=None, on_trade_open=_o, on_trade_close=_c, max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    return [r for r in rows.values() if "net_r" in r]

def attempt(seq_r, seq_day, start_i, R, target):
    """Play forward from start_i. Returns (passed, n_trades, days_used, reason)."""
    eq = START; day = seq_day[start_i]; day_start_eq = eq; day_pnl = 0.0
    valid_days = 0; n = 0
    for j in range(start_i, min(start_i + MAX_TRADES_WINDOW, len(seq_r))):
        d = seq_day[j]
        if d != day:  # day rollover — settle previous day
            if day_pnl >= VALID_DAY: valid_days += 1
            day = d; day_start_eq = eq; day_pnl = 0.0
        risk_dollar = R * eq
        pnl = risk_dollar * seq_r[j]
        eq += pnl; day_pnl += pnl; n += 1
        # gates (close-based)
        if eq < MAXDD_FLOOR: return (False, n, valid_days, "MAXDD")
        if (day_start_eq - eq) > DAILY_DD * day_start_eq: return (False, n, valid_days, "DAILYDD")
        if eq >= target and (valid_days + (1 if day_pnl >= VALID_DAY else 0)) >= MIN_VALID_DAYS:
            return (True, n, valid_days, "PASS")
    return (False, n, valid_days, "TIMEOUT")

def montecarlo(trades, R, target, n_att=3000, seed=0):
    rng = np.random.default_rng(seed)
    r = np.array([t["net_r"] for t in trades])
    days = np.array([pd.Timestamp(t["entry_ts"]).normalize().value for t in trades])
    starts = rng.integers(0, len(trades) - MAX_TRADES_WINDOW, size=n_att)
    passes = 0; ntr = []; reasons = {}
    for s in starts:
        ok, nt, vd, why = attempt(r, days, int(s), R, target)
        passes += ok; reasons[why] = reasons.get(why, 0) + 1
        if ok: ntr.append(nt)
    return passes / n_att, (np.median(ntr) if ntr else None), reasons

if __name__ == "__main__":
    log("="*78); log(f"GFT 2-STEP GOAT sim — A+D strict, 5K account   {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*78)
    log("RULES: P1 +8% P2 +6% | dailyDD 4% of day-start | maxDD 10% STATIC ($4500 floor) | >=3 valid days")
    log("LIMITATION: gates checked on CLOSE-based equity — real intraday DD worse -> these are UPPER-BOUND pass rates.")
    m5 = pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15")
    log(f"DATA: M15 bars={len(frame):,}  {frame.timestamp.iloc[0]} .. {frame.timestamp.iloc[-1]}")
    a = capture(functools.partial(FibV2IntradayA, strict_after=True), frame, 48)
    d = capture(functools.partial(FibV2IntradayD, strict_after=True), frame, 96)
    ad = sorted(a + d, key=lambda t: t["entry_ts"])
    r = np.array([t["net_r"] for t in ad])
    yrs = (pd.Timestamp(ad[-1]["entry_ts"]) - pd.Timestamp(ad[0]["entry_ts"])).days / 365.25
    log(f"A+D trades={len(ad)} netR={r.sum():+.0f} avgR={r.mean():+.4f} tr/yr={len(ad)/yrs:.0f} tr/mo={len(ad)/yrs/12:.0f}")

    log("\n=== PHASE-1 PASS (+8%) by risk ===")
    log(f"  {'risk':>5} | {'P(pass)':>8} {'medTrades':>10} | fail reasons")
    for R in (0.0025, 0.005, 0.0075, 0.01, 0.015):
        p, med, rs = montecarlo(ad, R, P1)
        log(f"  {R*100:>4.2f}% | {p*100:>6.1f}% {str(med):>10} | {rs}")

    log("\n=== PHASE-2 PASS (+6%) by risk ===")
    for R in (0.005, 0.0075, 0.01):
        p, med, rs = montecarlo(ad, R, P2)
        log(f"  {R*100:>4.2f}% | P2 pass {p*100:>6.1f}%  medTrades={med}  {rs}")

    log("\n=== FUNDED $ (per month, ONE 5K account) — fixed-fractional at R, no compounding drift ===")
    tr_mo = len(ad) / yrs / 12
    for R in (0.005, 0.0075, 0.01):
        # expected monthly return ~ tr/mo * avgR * R  (arithmetic, first-order)
        mret = tr_mo * r.mean() * R
        gross = START * mret
        log(f"  R={R*100:.2f}%: E[monthly return]~{mret*100:+.1f}%  gross~${gross:+,.0f}/mo  "
            f"payout@80%=${gross*0.8:+,.0f}  @100%=${gross:+,.0f}   (before variance/DD haircut)")
    log("\nNOTE: monthly $ is arithmetic-mean expectancy; realized is lumpy (some months negative).")
    log("Combined P1*P2 challenge pass ~ product of the two above at the chosen risk.")
    LOG.close()
