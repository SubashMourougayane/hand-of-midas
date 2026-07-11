#!/usr/bin/env python3
"""GFT INSTANT FUNDING PRO sim for A+D (hostile-audited).

Rules (Instant PRO, GFT FAQ 2026-07): 4% TRAILING drawdown on equity (floor rises with
equity peak), NO daily DD, but -2% FLOATING PnL = instant permanent closure, >=5 valid
days (0.5% each) before first payout, 80% split (100% add-on), bi-weekly payout, 20%
consistency (payout-blocking not fatal).

Two killers vs the 2-step's 10% static max DD:
  (a) 4% trailing (~2.5x tighter, AND resets up) — simulated here on close equity.
  (b) -2% FLOATING open PnL — INTRADAY; A+D runs up to 4 concurrent (A long + D short),
      so combined open drawdown hits -2% easily. NOT fully simulable without intraday MAE;
      approximated by a concurrent-open-risk bound + flagged as the DOMINANT killer.

Reports P(survive to first payout) + median trades-to-breach at low risk. Close-based =>
UPPER bound (real intraday floating breaches sooner).
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
LOG = open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/INSTANT_PRO_SIM_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log", "w")
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s+"\n"); LOG.flush()

START = 2500.0
TRAIL = 0.04       # 4% trailing on equity peak
FLOAT_KILL = 0.02  # -2% floating = instant close
VALID_DAY = 0.005 * START
MIN_DAYS = 5
PAYOUT_TARGET = 1.05 * START   # assume you'd bank a first payout ~+5% (illustrative)
WINDOW = 1500

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

def attempt(r, days, start_i, R):
    """Trailing-4% survival to first payout. Returns (survived_to_payout, n, reason)."""
    eq = START; peak = START; day = days[start_i]; day_pnl = 0.0; valid = 0; n = 0
    for j in range(start_i, min(start_i + WINDOW, len(r))):
        if days[j] != day:
            if day_pnl >= VALID_DAY: valid += 1
            day = days[j]; day_pnl = 0.0
        pnl = R * eq * r[j]; eq += pnl; day_pnl += pnl; n += 1
        peak = max(peak, eq)
        if eq < peak * (1 - TRAIL): return (False, n, "TRAIL_DD")
        if eq >= PAYOUT_TARGET and (valid + (1 if day_pnl >= VALID_DAY else 0)) >= MIN_DAYS:
            return (True, n, "PAYOUT")
    return (False, n, "TIMEOUT")

def mc(trades, R, n_att=3000, seed=0):
    rng = np.random.default_rng(seed)
    r = np.array([t["net_r"] for t in trades])
    days = np.array([pd.Timestamp(t["entry_ts"]).normalize().value for t in trades])
    st = rng.integers(0, len(trades) - WINDOW, size=n_att)
    surv = 0; ntr = []; reasons = {}
    for s in st:
        ok, nt, why = attempt(r, days, int(s), R); surv += ok
        reasons[why] = reasons.get(why, 0) + 1
        if ok: ntr.append(nt)
    return surv / n_att, (np.median(ntr) if ntr else None), reasons

if __name__ == "__main__":
    log("="*78); log(f"GFT INSTANT PRO sim — A+D strict, 2.5K account   {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"); log("="*78)
    log("RULES: 4% TRAILING DD on equity | NO daily DD | -2% FLOATING = instant close | >=5 valid days")
    log("close-based trailing => UPPER bound. -2% floating NOT simulated (intraday) — flagged separately.")
    m5 = pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15")
    a = capture(functools.partial(FibV2IntradayA, strict_after=True), frame, 48)
    d = capture(functools.partial(FibV2IntradayD, strict_after=True), frame, 96)
    ad = sorted(a + d, key=lambda t: t["entry_ts"])
    r = np.array([t["net_r"] for t in ad])
    log(f"A+D trades={len(ad)} avgR={r.mean():+.4f}")
    log("\n=== SURVIVE 4% TRAILING to a first +5% payout (>=5 valid days) ===")
    log(f"  {'risk':>6} | {'P(survive)':>10} {'medTrades':>10} | reasons")
    for R in (0.001, 0.0025, 0.005, 0.0075):
        p, med, rs = mc(ad, R)
        log(f"  {R*100:>5.2f}% | {p*100:>8.1f}% {str(med):>10} | {rs}")
    log("\nFLOATING -2% KILLER (not in sim): A+D allows up to 4 concurrent (A long + D short).")
    log("At R=0.5%, 4 open near-stop => ~2% floating => instant close on a routine XAU spike.")
    log("Only R<=~0.25% keeps worst-case concurrent floating under -2% (4*0.25%=1%). Even then trailing-4% bites.")
    LOG.close()
