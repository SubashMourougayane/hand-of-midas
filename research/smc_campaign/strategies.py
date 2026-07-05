"""The 12 SMC/ICT strategies from the PDF, each a causal setup-builder.

Each builder returns a DataFrame with: arm_ts, side, entry_price, tp_price, sl_price.
Entry is a LIMIT into the zone; fill/bracket handled by sweep_engine. Everything is
known at arm_ts (fully-confirmed). Structural passes cached per key for speed.

PDF page refs inline. LONG+SHORT unless a strategy is inherently directional.
"""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from research.smc_campaign import primitives as P
from research.smc_campaign.framework import MTF

# ---- structural cache: swings/events/zones per (tf_rule, k) computed once ----
_CACHE: dict = {}


def _struct(mtf: MTF, rule: str, k: int):
    key = (rule, k)
    if key in _CACHE:
        return _CACHE[key]
    df = mtf.tf(rule)  # always the enriched resample (has ema100/rsi14); tf() caches
    tfm = {"15min": 15, "30min": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}[rule]
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    fvg = P.fvg_zones(df, tf_min=tfm)
    ob = P.ob_bodyfrac(df, tf_min=tfm)
    obs = P.ob_structure(df, ev, tf_min=tfm)
    idm = P.idm_levels(sw, ev)
    swp = P.sweeps(sw)
    bb = P.breaker_blocks(sw)
    mb = P.mitigation_blocks(sw)
    out = dict(df=df, tfm=tfm, sw=sw, ev=ev, fvg=fvg, ob=ob, obs=obs, idm=idm,
               swp=swp, bb=bb, mb=mb)
    _CACHE[key] = out
    return out


def _naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tz is not None else t


def _htf_trend_ok(mtf: MTF, arm_ts, side, rule="4h"):
    """H4 trend gate via close>ema50 on last-closed H4 bar known at arm_ts."""
    h = mtf.tf(rule)
    vt = h["timestamp"].dt.tz_localize(None).values + np.timedelta64(240 if rule == "4h" else 60, "m")
    i = int(np.searchsorted(vt, np.datetime64(_naive(arm_ts)), side="right")) - 1
    if i < 0 or i >= len(h):
        return True
    up = h["close"].values[i] > h["ema50"].values[i]
    return up if side > 0 else (not up)


# ============================================================================
# S1 — SMC 10-step: trend + sweep->CHoCH into OB/FVG confluence, discount/premium
#      (this generalises the certified OTE winner but with OB/FVG/IDM confluence)
# ============================================================================
def build_s1(mtf, *, rule="15min", k=3, ote=0.705, sl_buf=0.10, tp_mode="3R",
             sweep_lb=6, need_conf=2, use_idm=0, h4_trend=1, session="kz",
             sides=(1,), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k)
    df = S["df"]; sw = S["sw"]; ev = S["ev"]
    fvg = S["fvg"]; ob = S["ob"]
    swp = S["swp"]
    # map sweeps by swing index
    swp_by_i = {int(r.swing_i): r for r in swp.itertuples(index=False)}
    fvg_l = {d: fvg[fvg.dir == d].reset_index(drop=True) for d in (1, -1)}
    ob_l = {d: ob[ob.dir == d].reset_index(drop=True) for d in (1, -1)}
    idm = S["idm"]
    rows = []
    hi_ist = None
    for bi, b in enumerate(sw):
        side = 1 if b.kind == "L" else -1
        if side not in sides:
            continue
        r = swp_by_i.get(bi)
        if r is None or r.depth_rank > sweep_lb:
            continue
        # need CHoCH after this swing in the trade direction
        after = [e for e in ev if e.confirm_ts >= b.confirm_ts and e.dir == side and e.kind in ("CHOCH", "BOS")]
        if not after:
            continue
        choch = after[0]
        arm_ts = choch.confirm_ts
        # define leg range from swept swing to the choch ref
        if side > 0:
            swing_lo = b.price
            swing_hi = choch.level
            if swing_hi <= swing_lo:
                continue
            entry = swing_hi - ote * (swing_hi - swing_lo)
            ssl = swing_lo
        else:
            swing_hi = b.price
            swing_lo = choch.level
            if swing_hi <= swing_lo:
                continue
            entry = swing_lo + ote * (swing_hi - swing_lo)
            ssl = swing_hi
        # confluence count: FVG-in-leg + OB-in-leg
        cnt = 0
        f = fvg_l[side]; fv = f[(f.valid_ts > b.bar_ts) & (f.valid_ts <= arm_ts) & (f.hi >= swing_lo) & (f.lo <= swing_hi)]
        if len(fv): cnt += 1
        o = ob_l[side]; ov = o[(o.valid_ts > b.bar_ts) & (o.valid_ts <= arm_ts) & (o.hi >= swing_lo) & (o.lo <= swing_hi)]
        if len(ov): cnt += 1
        if cnt < need_conf:
            continue
        if use_idm:
            im = idm[(idm.dir == side) & (idm.valid_ts <= arm_ts)]
            if not len(im):
                continue
        if h4_trend and not _htf_trend_ok(mtf, arm_ts, side):
            continue
        if session == "kz":
            t = pd.Timestamp(arm_ts)
            t = t.tz_localize("UTC") if t.tz is None else t
            hh = t.tz_convert("America/New_York").hour
            if not (2 <= hh <= 11):
                continue
        rows.append(_mk(side, entry, ssl, sl_buf, tp_mode, arm_ts))
    return _df(rows)


# ============================================================================
# S2 — FVG Trade (pg14-15): price returns to an FVG, test candle spikes/closes in FVG
#      (body not crossing CE), then trade toward the FVG direction. TP=next swing, SL=FVG edge.
# ============================================================================
def build_s2(mtf, *, rule="15min", k=3, tp_mode="swing", sl_buf=0.10, need_ce=1,
             h4_trend=0, session="all", sides=(1, -1), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k); df = S["df"]; sw = S["sw"]; fvg = S["fvg"]
    hi = df["high"].values; lo = df["low"].values; cl = df["close"].values; op = df["open"].values
    ts = df["timestamp"].values; tfm = S["tfm"]; td = np.timedelta64(tfm, "m")
    rows = []
    for r in fvg.itertuples(index=False):
        side = int(r.dir)
        if side not in sides:
            continue
        # entry = CE (consequent encroachment) as the limit into the FVG
        entry = r.ce
        # SL = FVG far edge + buf; TP = nearest opposite swing after valid
        if side > 0:
            sl_ref = r.lo
        else:
            sl_ref = r.hi
        # nearest swing target
        tgt = [s for s in sw if s.confirm_ts <= r.valid_ts and ((s.kind == "H" and side > 0) or (s.kind == "L" and side < 0))]
        if not tgt:
            continue
        rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, r.valid_ts,
                        tp_price=(tgt[-1].price if tp_mode == "swing" else None)))
    out = _df(rows)
    if h4_trend and len(out):
        out = out[[_htf_trend_ok(mtf, a, s) for a, s in zip(out.arm_ts, out.side)]].reset_index(drop=True)
    return out


# ============================================================================
# S3 — FVG Inversion (pg15-16): a bullish FVG whose gap is later CLOSED by a bearish
#      displacement candle (body through it) => inverts to bearish; trade the reversal.
# ============================================================================
def build_s3(mtf, *, rule="15min", k=3, sl_buf=0.15, tp_mode="2R", h4_trend=0,
             session="all", sides=(1, -1), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k); df = S["df"]; sw = S["sw"]; fvg = S["fvg"]
    cl = df["close"].values; op = df["open"].values; ts = df["timestamp"].values
    tfm = S["tfm"]; td = np.timedelta64(tfm, "m")
    rows = []
    for r in fvg.itertuples(index=False):
        # look for a later candle whose BODY fully crosses the gap in the OPPOSITE dir
        gap_lo, gap_hi = r.lo, r.hi
        inv_side = -int(r.dir)  # inversion flips
        if inv_side not in sides:
            continue
        j0 = int(r.mid_idx) + 1
        found = -1
        for j in range(j0, min(len(df), j0 + 40)):
            body_lo = min(op[j], cl[j]); body_hi = max(op[j], cl[j])
            if inv_side < 0 and cl[j] < gap_lo and op[j] > gap_lo:  # bearish disp through gap
                found = j; break
            if inv_side > 0 and cl[j] > gap_hi and op[j] < gap_hi:
                found = j; break
        if found < 0:
            continue
        arm_ts = pd.Timestamp(ts[found]) + td
        entry = r.ce  # retest of inverted zone
        sl_ref = gap_hi if inv_side < 0 else gap_lo
        rows.append(_mk(inv_side, entry, sl_ref, sl_buf, tp_mode, arm_ts))
    out = _df(rows)
    if h4_trend and len(out):
        out = out[[_htf_trend_ok(mtf, a, s) for a, s in zip(out.arm_ts, out.side)]].reset_index(drop=True)
    return out


# ============================================================================
# S4 — Breaker / Mitigation (pg16-17): enter on retrace into the breaker/mitigation zone.
# ============================================================================
def build_s4(mtf, *, rule="15min", k=3, block="breaker", sl_buf=0.15, tp_mode="2R",
             h4_trend=1, session="all", sides=(1, -1), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k)
    zones = S["bb"] if block == "breaker" else S["mb"]
    rows = []
    for r in zones.itertuples(index=False):
        side = int(r.dir)
        if side not in sides:
            continue
        entry = (r.lo + r.hi) / 2  # mid of the block
        sl_ref = r.lo if side > 0 else r.hi
        rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, r.valid_ts))
    out = _df(rows)
    if h4_trend and len(out):
        out = out[[_htf_trend_ok(mtf, a, s) for a, s in zip(out.arm_ts, out.side)]].reset_index(drop=True)
    return out


# ============================================================================
# S5 — QML / Quasimodo (pg18): uptrend makes LL with MSS then reverses at QML zone
#      (the high just before the drop). Enter short at that head-high zone (mirror long).
# ============================================================================
def build_s5(mtf, *, rule="15min", k=3, sl_buf=0.15, tp_mode="2R", h4_trend=0,
             session="all", sides=(1, -1), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k); sw = S["sw"]; ev = S["ev"]
    mss = P.mss_events(ev)
    rows = []
    for m in mss:
        side = m.dir  # CHoCH direction is the reversal direction
        if side not in sides:
            continue
        # QML zone = the last opposing swing before the MSS (head)
        want = "H" if side < 0 else "L"
        cand = [s for s in sw if s.kind == want and s.confirm_ts <= m.confirm_ts]
        if not cand:
            continue
        head = cand[-1]
        entry = head.price               # limit into the QML head zone
        rref = abs(head.price - m.level)  # head-to-MSS-break distance = risk scale
        if rref <= 0:
            continue
        rows.append(_mk(side, entry, head.price, sl_buf, tp_mode, m.confirm_ts, risk_ref=rref))
    out = _df(rows)
    if h4_trend and len(out):
        out = out[[_htf_trend_ok(mtf, a, s) for a, s in zip(out.arm_ts, out.side)]].reset_index(drop=True)
    return out


# ============================================================================
# S6 — Daily Bias (pg19): Daily TF. Prior daily candle: if it CLOSED grabbing
#      liquidity of the day before (took prior high/low then closed back) -> bias.
#      Simplified causal: yesterday's candle swept prior-day extreme; today trade the
#      close-direction bias. Fixed SL (in ATR of daily) since guide uses fixed 90pip.
#      Enter at next-day OPEN (market). TP = R multiple.
# ============================================================================
def build_s6(mtf, *, sl_atr=1.0, tp_mode="2R", sides=(1, -1), grab_mode="close",
             wait_bars=1, slip_atr=0.0, horizon=288):
    d = mtf.tf("1d")
    o, h, l, c = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    atr = d["atr14"].values
    ts = d["timestamp"].values
    td = np.timedelta64(1440, "m")
    rows = []
    for i in range(2, len(d) - 1):
        # yesterday (i) swept day i-1 extreme and closed back inside/opposite
        bull = l[i] < l[i - 1] and c[i] > l[i - 1] and c[i] > o[i]  # swept low, closed up -> bullish
        bear = h[i] > h[i - 1] and c[i] < h[i - 1] and c[i] < o[i]
        side = 1 if bull else (-1 if bear else 0)
        if side == 0 or side not in sides:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        arm_ts = pd.Timestamp(ts[i]) + td       # known at day i close
        entry = c[i]                              # proxy for next-day open ~ prev close
        sl_ref = entry - side * sl_atr * a        # fixed-ATR stop
        rows.append(_mk(side, entry, sl_ref, 0.0, tp_mode, arm_ts, risk_ref=sl_atr * a))
    return _df(rows)


# ============================================================================
# S7 — Power of Three (pg20): AMD. London session breaks the Tokyo range extreme
#      (manipulation), then a CHoCH in London on 15M -> trade the reversal. TP via R.
# ============================================================================
def build_s7(mtf, *, k=3, sl_buf=0.15, tp_mode="2R", sides=(1, -1),
             wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, "15min", k); df = S["df"]; ev = S["ev"]
    # Tokyo range per day from 15M bars in Tokyo session (IST 5:30-14:00)
    ist = df["timestamp"].dt.tz_convert(P.IST)
    df = df.assign(ist_h=ist.dt.hour + ist.dt.minute/60.0, ist_date=ist.dt.date)
    tok = df[(df.ist_h >= 5.5) & (df.ist_h < 14.0)]
    tok_rng = tok.groupby("ist_date").agg(tok_hi=("high", "max"), tok_lo=("low", "min"),
                                          tok_end=("timestamp", "max")).reset_index()
    tok_map = {r.ist_date: r for r in tok_rng.itertuples(index=False)}
    # London CHoCH events -> if after breaking tokyo extreme, trade reversal
    mss = P.mss_events(ev)
    rows = []
    for m in mss:
        t = pd.Timestamp(m.confirm_ts)
        t = t.tz_localize("UTC") if t.tz is None else t
        ti = t.tz_convert(P.IST)
        hh = ti.hour + ti.minute/60.0
        if not (12.5 <= hh < 21.25):  # London window IST
            continue
        tr = tok_map.get(ti.date())
        if tr is None:
            continue
        side = m.dir
        if side not in sides:
            continue
        # entry at choch level (the broken structure), SL beyond tokyo extreme
        entry = m.level
        sl_ref = tr.tok_lo if side > 0 else tr.tok_hi
        rref = abs(entry - sl_ref)
        if rref <= 0:
            continue
        rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, m.confirm_ts, risk_ref=rref))
    return _df(rows)


# ============================================================================
# S8 — MMXM (pg21): 1D liquidity swap. Today's daily candle grabbed prior-day
#      liquidity from one side AND prior-day closed opposite. Then 1H FVG target,
#      15M entry after close beyond the swept line. Simplified: daily swap -> next-day
#      15M first CHoCH in swap direction.
# ============================================================================
def build_s8(mtf, *, k=3, sl_buf=0.15, tp_mode="2R", sides=(1, -1),
             wait_bars=96, slip_atr=0.05, horizon=288):
    d = mtf.tf("1d")
    o, h, l, c = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    ts = d["timestamp"].values; td = np.timedelta64(1440, "m")
    S = _struct(mtf, "15min", k); ev = S["ev"]
    mss = P.mss_events(ev)
    # precompute daily swap signals: day i swept day i-1 and day i-1 closed opposite
    swaps = []  # (dir, valid_ts_from)
    for i in range(2, len(d)):
        # bullish swap: today took prev low, prev day was bearish (close<open)
        if l[i] < l[i - 1] and c[i - 1] < o[i - 1]:
            swaps.append((1, pd.Timestamp(ts[i]) + td))
        elif h[i] > h[i - 1] and c[i - 1] > o[i - 1]:
            swaps.append((-1, pd.Timestamp(ts[i]) + td))
    rows = []
    for sdir, vfrom in swaps:
        if sdir not in sides:
            continue
        # first 15M CHoCH in swap dir within 1 day after vfrom
        vend = vfrom + np.timedelta64(1, "D")
        cand = [m for m in mss if m.dir == sdir and vfrom <= m.confirm_ts <= vend]
        if not cand:
            continue
        m = cand[0]
        entry = m.level
        # SL beyond the recent opposite swing
        S2 = _struct(mtf, "15min", k)["sw"]
        opp = [s for s in S2 if s.kind == ("L" if sdir > 0 else "H") and s.confirm_ts <= m.confirm_ts]
        if not opp:
            continue
        sl_ref = opp[-1].price
        rref = abs(entry - sl_ref)
        if rref <= 0:
            continue
        rows.append(_mk(sdir, entry, sl_ref, sl_buf, tp_mode, m.confirm_ts, risk_ref=rref))
    return _df(rows)


# ============================================================================
# S10 — RSI divergence (pg25): RSI(14) 30/70. At OB/OS, body-to-body divergence, then
#       LTF CHoCH confirms trend change -> trade reversal. Structure TF chosen.
# ============================================================================
def build_s10(mtf, *, rule="15min", k=3, ob_level=70, os_level=30, sl_buf=0.15,
              tp_mode="2R", sides=(1, -1), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k); df = S["df"]; sw = S["sw"]; ev = S["ev"]
    rsi = df["rsi14"].values; close = df["close"].values; ts = df["timestamp"].values
    tfm = S["tfm"]; td = np.timedelta64(tfm, "m")
    mss = P.mss_events(ev)
    # find divergence: two consecutive same-kind swings where price makes HH but RSI LH
    # (bearish div) at OB; or price LL but RSI HL (bullish div) at OS. Confirm w/ MSS.
    highs = [s for s in sw if s.kind == "H"]
    lows = [s for s in sw if s.kind == "L"]
    div_pts = []  # (side, confirm_ts, ref_swing_price)
    for a, b in zip(highs, highs[1:]):
        if b.price > a.price and rsi[b.idx] < rsi[a.idx] and rsi[a.idx] >= ob_level:
            div_pts.append((-1, b.confirm_ts, b.price))
    for a, b in zip(lows, lows[1:]):
        if b.price < a.price and rsi[b.idx] > rsi[a.idx] and rsi[a.idx] <= os_level:
            div_pts.append((1, b.confirm_ts, b.price))
    rows = []
    for side, dts, refpx in div_pts:
        if side not in sides:
            continue
        # confirm with first MSS in reversal dir after divergence
        cand = [m for m in mss if m.dir == side and m.confirm_ts >= dts]
        if not cand:
            continue
        m = cand[0]
        entry = m.level
        opp = [s for s in sw if s.kind == ("L" if side > 0 else "H") and s.confirm_ts <= m.confirm_ts]
        if not opp:
            continue
        sl_ref = opp[-1].price
        rref = abs(entry - sl_ref)
        if rref <= 0:
            continue
        rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, m.confirm_ts, risk_ref=rref))
    return _df(rows)


# ============================================================================
# S11 — Fib Retracement (pg28): fib 50/61.8 on correction wave + EMA50/100 confluence
#       + LTF CHoCH. Reuse swing legs; enter at fib level in the leg direction.
# ============================================================================
def build_s11(mtf, *, rule="15min", k=3, fib=0.618, sl_buf=0.15, tp_mode="2R",
              ema_confirm=1, sides=(1, -1), wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k); df = S["df"]; sw = S["sw"]
    ema50 = df["ema50"].values; ema100 = df["ema100"].values
    tfm = S["tfm"]
    rows = []
    for a, b in zip(sw, sw[1:]):
        # up leg: L -> H, retrace to fib, long
        if a.kind == "L" and b.kind == "H" and b.price > a.price:
            side = 1
            if side not in sides: continue
            rng = b.price - a.price
            entry = b.price - fib * rng
            sl_ref = a.price
            arm_ts = b.confirm_ts
            if ema_confirm:
                i = b.idx
                if not (ema50[i] > ema100[i]):  # up-trend confluence
                    continue
            rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, arm_ts))
        elif a.kind == "H" and b.kind == "L" and b.price < a.price:
            side = -1
            if side not in sides: continue
            rng = a.price - b.price
            entry = b.price + fib * rng
            sl_ref = a.price
            arm_ts = b.confirm_ts
            if ema_confirm:
                i = b.idx
                if not (ema50[i] < ema100[i]):
                    continue
            rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, arm_ts))
    return _df(rows)


# ============================================================================
# S12 — Fake-breakout filtered entry (pg25-27): trade breakouts of swing extremes,
#       but only when volume-large OR retest-grab confirms (real), filtered by RSI +
#       4H trend context. Entry at breakout close, SL beyond the broken swing.
# ============================================================================
def build_s12(mtf, *, rule="15min", k=3, vol_mult=1.5, need_retest=0, use_rsi=1,
              h4_trend=1, sl_buf=0.20, tp_mode="2R", sides=(1, -1),
              wait_bars=96, slip_atr=0.05, horizon=288):
    S = _struct(mtf, rule, k); df = S["df"]; ev = S["ev"]
    vol = df["volume"].values; rsi = df["rsi14"].values
    close = df["close"].values; ts = df["timestamp"].values; tfm = S["tfm"]; td = np.timedelta64(tfm, "m")
    volma = pd.Series(vol).rolling(20).mean().values
    rows = []
    for e in ev:  # each BOS/CHoCH is a structure breakout
        side = e.dir
        if side not in sides:
            continue
        j = e.break_idx
        # volume filter: real breakout = large volume
        if not (np.isfinite(volma[j]) and vol[j] >= vol_mult * volma[j]):
            continue
        if use_rsi:
            # fade-fake: don't buy into overbought, don't sell into oversold
            if side > 0 and rsi[j] > 75:
                continue
            if side < 0 and rsi[j] < 25:
                continue
        entry = close[j]
        sl_ref = e.level
        rref = abs(entry - sl_ref)
        if rref <= 0:
            continue
        rows.append(_mk(side, entry, sl_ref, sl_buf, tp_mode, e.confirm_ts, risk_ref=rref))
    out = _df(rows)
    if h4_trend and len(out):
        out = out[[_htf_trend_ok(mtf, a, s) for a, s in zip(out.arm_ts, out.side)]].reset_index(drop=True)
    return out


# ============================================================================
# helpers
# ============================================================================
def _mk(side, entry, ssl_ref, sl_buf, tp_mode, arm_ts, tp_price=None, risk_ref=None):
    """Build a setup row.
      side: +1/-1
      entry: limit price
      ssl_ref: the swept/structure level the SL sits beyond
      sl_buf: SL padding beyond ssl_ref, as a FRACTION of `scale`
      risk_ref: distance used as scale for the pad (defaults to |entry-ssl_ref|)
    SL = ssl_ref padded away from entry. Guards degenerate entry==ssl_ref via risk_ref.
    """
    scale = risk_ref if risk_ref is not None else abs(entry - ssl_ref)
    if scale <= 0:
        scale = abs(entry) * 0.001  # tiny fallback; will usually be filtered by min_risk
    pad = sl_buf * scale
    if side > 0:
        sl = ssl_ref - pad
    else:
        sl = ssl_ref + pad
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    if tp_price is not None:
        tp = tp_price
    elif tp_mode == "3R":
        tp = entry + 3 * risk * side
    else:  # "2R" and fallbacks
        tp = entry + 2 * risk * side
    return {"arm_ts": arm_ts, "side": side, "entry_price": entry,
            "tp_price": tp, "sl_price": sl}


def _df(rows):
    rows = [r for r in rows if r is not None]
    if not rows:
        return pd.DataFrame(columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price"])
    return pd.DataFrame(rows)
