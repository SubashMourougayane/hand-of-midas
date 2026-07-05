"""Fast universe/price split for the 12 SMC strategies.

Design: for each strategy, build a UNIVERSE of candidate setups ONCE per structural
key (rule,k) — a DataFrame with all metadata columns needed by any config. Then each
sweep config is a cheap vectorised FILTER + PRICE over that universe (no rebuild).

price_* returns setups df (arm_ts, side, entry_price, tp_price, sl_price[, fill_mode])
ready for sweep_engine.fill_setups. Everything causal: universe rows carry arm_ts =
the fully-confirmed setup time; pricing uses only leg geometry known by then.

Universes cached in _UNIV keyed by (strategy, rule, k[, extra]).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.smc_campaign import primitives as P
from research.smc_campaign.framework import MTF

_UNIV: dict = {}
_TFM = {"15min": 15, "30min": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}


def _naive(s):
    s = pd.to_datetime(pd.Series(s))
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_localize(None)
    return s


def _h4_up_at(mtf: MTF, arm_ts_series):
    """Vectorised H4 trend-up flag known at each arm_ts (close>ema50 on last-closed H4)."""
    h = mtf.tf("4h")
    vt = (h["timestamp"].dt.tz_localize(None) + pd.Timedelta(minutes=240)).values.astype("datetime64[ns]")
    up = (h["close"].values > h["ema50"].values).astype(np.int8)
    arm = _naive(arm_ts_series).values.astype("datetime64[ns]")
    i = np.searchsorted(vt, arm, side="right") - 1
    ok = i >= 0
    out = np.zeros(len(arm), dtype=np.int8)
    out[ok] = up[i[ok]]
    return out


def _ny_hour(arm_ts_series):
    t = pd.to_datetime(pd.Series(arm_ts_series))
    if getattr(t.dt, "tz", None) is None:
        t = t.dt.tz_localize("UTC")
    return t.dt.tz_convert("America/New_York").dt.hour.values


def _price(side, entry, ssl_ref, sl_buf, tp_mode, scale):
    """Vectorised SL/TP. side/entry/ssl_ref/scale arrays. Returns sl, tp, risk."""
    scale = np.where(scale <= 0, np.abs(entry) * 1e-3, scale)
    pad = sl_buf * scale
    sl = np.where(side > 0, ssl_ref - pad, ssl_ref + pad)
    risk = np.abs(entry - sl)
    mult = np.where(np.asarray(tp_mode) == "3R", 3.0, 2.0) if isinstance(tp_mode, np.ndarray) else (3.0 if tp_mode == "3R" else 2.0)
    tp = entry + mult * risk * side
    return sl, tp, risk


# ============================================================================
# S1 — sweep -> CHoCH -> OTE, with OB/FVG confluence counts + IDM + sessions
# Universe row per (swept swing -> first same-dir CHoCH): carries swing_lo/hi,
# sweep depth, fvg/ob-in-leg flags, idm flag, h4up, ny_hour, arm_ts, side.
# ============================================================================
def universe_s1(mtf, rule, k):
    key = ("s1", rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    fvg = P.fvg_zones(df, tf_min=tfm); ob = P.ob_bodyfrac(df, tf_min=tfm)
    idm = P.idm_levels(sw, ev)
    swp = P.sweeps(sw)
    swp_by = {int(r.swing_i): r for r in swp.itertuples(index=False)}
    # index events by (dir) sorted on confirm_ts for fast "first after"
    ev_up = sorted([e for e in ev if e.dir > 0], key=lambda e: e.confirm_ts)
    ev_dn = sorted([e for e in ev if e.dir < 0], key=lambda e: e.confirm_ts)
    ev_up_ts = np.array([np.datetime64(_naive(pd.Series([e.confirm_ts]))[0]) for e in ev_up]) if ev_up else np.array([], dtype="datetime64[ns]")
    ev_dn_ts = np.array([np.datetime64(_naive(pd.Series([e.confirm_ts]))[0]) for e in ev_dn]) if ev_dn else np.array([], dtype="datetime64[ns]")
    fvg_l = {d: fvg[fvg.dir == d].reset_index(drop=True) for d in (1, -1)}
    ob_l = {d: ob[ob.dir == d].reset_index(drop=True) for d in (1, -1)}
    idm_l = {d: idm[idm.dir == d].reset_index(drop=True) for d in (1, -1)}

    rows = []
    for bi, b in enumerate(sw):
        side = 1 if b.kind == "L" else -1
        r = swp_by.get(bi)
        if r is None:
            continue
        depth = int(r.depth_rank)
        bconf = np.datetime64(_naive(pd.Series([b.confirm_ts]))[0])
        evts = ev_up_ts if side > 0 else ev_dn_ts
        evlist = ev_up if side > 0 else ev_dn
        pos = np.searchsorted(evts, bconf, side="left")
        if pos >= len(evlist):
            continue
        choch = evlist[pos]
        arm_ts = choch.confirm_ts
        if side > 0:
            swing_lo = b.price; swing_hi = choch.level
        else:
            swing_hi = b.price; swing_lo = choch.level
        if swing_hi <= swing_lo:
            continue
        # confluence flags (formed in leg lo_ts..arm_ts, overlapping range)
        f = fvg_l[side]
        fv = ((f.valid_ts > b.bar_ts) & (f.valid_ts <= arm_ts) & (f.hi >= swing_lo) & (f.lo <= swing_hi)).any()
        o = ob_l[side]
        ov = ((o.valid_ts > b.bar_ts) & (o.valid_ts <= arm_ts) & (o.hi >= swing_lo) & (o.lo <= swing_hi)).any()
        im = ((idm_l[side].valid_ts <= arm_ts)).any() if len(idm_l[side]) else False
        rows.append((arm_ts, side, swing_lo, swing_hi, depth, int(fv), int(ov), int(im)))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "swing_lo", "swing_hi", "depth",
                                    "fvg", "ob", "idm"])
    if len(u):
        u["h4up"] = _h4_up_at(mtf, u["arm_ts"])
        u["ny_hr"] = _ny_hour(u["arm_ts"])
    _UNIV[key] = u
    return u


def price_s1(mtf, *, rule, k, ote, sl_buf, tp_mode, sweep_lb, need_conf, use_idm,
             h4_trend, session, sides):
    u = universe_s1(mtf, rule, k)
    if len(u) == 0:
        return u
    m = u["side"].isin(sides) & (u["depth"] <= sweep_lb)
    conf = 3 + u["fvg"] + u["ob"]
    m &= conf >= need_conf
    if use_idm:
        m &= u["idm"] == 1
    if h4_trend:
        m &= np.where(u["side"] > 0, u["h4up"] == 1, u["h4up"] == 0)
    if session == "kz":
        m &= (u["ny_hr"] >= 2) & (u["ny_hr"] <= 11)
    s = u[m]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    rng = (s["swing_hi"] - s["swing_lo"]).values
    entry = np.where(side > 0, s["swing_hi"].values - ote * rng, s["swing_lo"].values + ote * rng)
    ssl = np.where(side > 0, s["swing_lo"].values, s["swing_hi"].values)
    sl, tp, risk = _price(side, entry, ssl, sl_buf, tp_mode, np.abs(entry - ssl))
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


def price_s1_short(mtf, *, rule, k, ote, sl_buf, tp_r, sweep_lb, need_conf,
                   trend_mode, session):
    """Short-only sweep->CHoCH->OTE, tailored levers.
      tp_r: arbitrary R multiple (shorts snap back -> allow 1R/1.5R).
      trend_mode: 'down' (h4 down, with-trend), 'off' (no gate), 'fade' (h4 UP -> fade
                  the uptrend, counter-trend short at premium).
    """
    u = universe_s1(mtf, rule, k)
    if len(u) == 0:
        return u
    m = (u["side"] == -1) & (u["depth"] <= sweep_lb)
    conf = 3 + u["fvg"] + u["ob"]
    m &= conf >= need_conf
    if trend_mode == "down":
        m &= u["h4up"] == 0
    elif trend_mode == "fade":
        m &= u["h4up"] == 1
    # 'off' = no trend gate
    if session == "kz":
        m &= (u["ny_hr"] >= 2) & (u["ny_hr"] <= 11)
    s = u[m]
    if len(s) == 0:
        return s
    rng = (s["swing_hi"] - s["swing_lo"]).values
    entry = s["swing_lo"].values + ote * rng          # premium zone for short
    ssl = s["swing_hi"].values                         # SL above swept high
    pad = sl_buf * np.abs(entry - ssl)
    sl = ssl + pad
    risk = np.abs(entry - sl)
    tp = entry - tp_r * risk
    side = np.full(len(s), -1.0)
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S2 — FVG trade: enter limit at CE, SL at far FVG edge, TP nearest swing / R.
# Universe = all FVGs with nearest-target swing price + h4up.
# ============================================================================
def universe_s2(mtf, rule, k):
    key = ("s2", rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    fvg = P.fvg_zones(df, tf_min=tfm)
    # nearest swing (dir-appropriate) confirmed before each fvg valid_ts, vectorised
    hi_sw = [(s.confirm_ts, s.price) for s in sw if s.kind == "H"]
    lo_sw = [(s.confirm_ts, s.price) for s in sw if s.kind == "L"]
    hi_ts = _naive(pd.Series([t for t, _ in hi_sw])).values.astype("datetime64[ns]") if hi_sw else np.array([], dtype="datetime64[ns]")
    hi_px = np.array([p for _, p in hi_sw])
    lo_ts = _naive(pd.Series([t for t, _ in lo_sw])).values.astype("datetime64[ns]") if lo_sw else np.array([], dtype="datetime64[ns]")
    lo_px = np.array([p for _, p in lo_sw])
    vts = _naive(fvg["valid_ts"]).values.astype("datetime64[ns]")
    tgt = np.full(len(fvg), np.nan)
    up = fvg["dir"].values > 0
    if len(hi_ts):
        ih = np.searchsorted(hi_ts, vts, side="right") - 1
        tgt = np.where(up & (ih >= 0), hi_px[np.clip(ih, 0, len(hi_px)-1)], tgt)
    if len(lo_ts):
        il = np.searchsorted(lo_ts, vts, side="right") - 1
        tgt = np.where((~up) & (il >= 0), lo_px[np.clip(il, 0, len(lo_px)-1)], tgt)
    u = fvg.rename(columns={"valid_ts": "arm_ts"}).copy()
    u["tgt"] = tgt
    u = u.dropna(subset=["tgt"]).reset_index(drop=True)
    if len(u):
        u["h4up"] = _h4_up_at(mtf, u["arm_ts"])
    _UNIV[key] = u
    return u


def price_s2(mtf, *, rule, k, tp_mode, sl_buf, h4_trend, sides):
    u = universe_s2(mtf, rule, k)
    if len(u) == 0:
        return u
    m = u["dir"].isin(sides)
    if h4_trend:
        m &= np.where(u["dir"] > 0, u["h4up"] == 1, u["h4up"] == 0)
    s = u[m]
    if len(s) == 0:
        return s
    side = s["dir"].values.astype(float)
    entry = s["ce"].values
    ssl = np.where(side > 0, s["lo"].values, s["hi"].values)
    sl, tp_r, risk = _price(side, entry, ssl, sl_buf, tp_mode, np.abs(entry - ssl))
    tp = s["tgt"].values if tp_mode == "swing" else tp_r
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S3 — FVG inversion: a gap later closed by opposite-body displacement. Universe =
# inverted zones with arm_ts (the displacement close) + ce/edge.
# ============================================================================
def universe_s3(mtf, rule, k):
    key = ("s3", rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    fvg = P.fvg_zones(df, tf_min=tfm)
    o = df["open"].values; c = df["close"].values; ts = df["timestamp"].values
    td = np.timedelta64(tfm, "m")
    n = len(df)
    rows = []
    for r in fvg.itertuples(index=False):
        inv = -int(r.dir)
        j0 = int(r.mid_idx) + 1
        end = min(n, j0 + 40)
        cj = c[j0:end]; oj = o[j0:end]
        if inv < 0:
            hit = np.where((cj < r.lo) & (oj > r.lo))[0]
        else:
            hit = np.where((cj > r.hi) & (oj < r.hi))[0]
        if len(hit) == 0:
            continue
        j = j0 + int(hit[0])
        arm_ts = pd.Timestamp(ts[j]) + td
        sslr = r.hi if inv < 0 else r.lo
        rows.append((arm_ts, inv, r.ce, sslr))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "ce", "ssl"])
    if len(u):
        u["h4up"] = _h4_up_at(mtf, u["arm_ts"])
    _UNIV[key] = u
    return u


def price_s3(mtf, *, rule, k, sl_buf, tp_mode, h4_trend, sides):
    u = universe_s3(mtf, rule, k)
    if len(u) == 0:
        return u
    m = u["side"].isin(sides)
    if h4_trend:
        m &= np.where(u["side"] > 0, u["h4up"] == 1, u["h4up"] == 0)
    s = u[m]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["ce"].values
    sl, tp, risk = _price(side, entry, s["ssl"].values, sl_buf, tp_mode, np.abs(entry - s["ssl"].values))
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S6 — Daily bias (market entry). Universe = qualifying daily candles.
# ============================================================================
def universe_s6(mtf):
    key = ("s6",)
    if key in _UNIV:
        return _UNIV[key]
    d = mtf.tf("1d")
    o, h, l, c = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    atr = d["atr14"].values; ts = d["timestamp"].values; td = np.timedelta64(1440, "m")
    rows = []
    for i in range(2, len(d) - 1):
        bull = l[i] < l[i-1] and c[i] > l[i-1] and c[i] > o[i]
        bear = h[i] > h[i-1] and c[i] < h[i-1] and c[i] < o[i]
        side = 1 if bull else (-1 if bear else 0)
        if side == 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        rows.append((pd.Timestamp(ts[i]) + td, side, c[i], atr[i]))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "entry", "atr"])
    _UNIV[key] = u
    return u


def price_s6(mtf, *, sl_atr, tp_mode, sides):
    u = universe_s6(mtf)
    if len(u) == 0:
        return u
    s = u[u["side"].isin(sides)]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["entry"].values
    scale = sl_atr * s["atr"].values
    ssl = entry - side * scale
    sl, tp, risk = _price(side, entry, ssl, 0.0, tp_mode, scale)
    out = pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                        "tp_price": tp, "sl_price": sl})
    out["fill_mode"] = "market"
    return out


# ============================================================================
# S8 — MMXM daily swap -> first 15M MSS in swap dir next day (market-ish limit).
# ============================================================================
def universe_s8(mtf, k):
    key = ("s8", k)
    if key in _UNIV:
        return _UNIV[key]
    d = mtf.tf("1d")
    o, h, l, c = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    ts = d["timestamp"].values; td = np.timedelta64(1440, "m")
    df = mtf.tf("15min")
    sw = P.find_swings(df, k=k, tf_min=15)
    ev = P.structure_events(df, sw, tf_min=15)
    mss = sorted(P.mss_events(ev), key=lambda e: e.confirm_ts)
    mss_ts = _naive(pd.Series([m.confirm_ts for m in mss])).values.astype("datetime64[ns]") if mss else np.array([], dtype="datetime64[ns]")
    rows = []
    for i in range(2, len(d)):
        if l[i] < l[i-1] and c[i-1] < o[i-1]:
            sdir = 1
        elif h[i] > h[i-1] and c[i-1] > o[i-1]:
            sdir = -1
        else:
            continue
        vfrom = pd.Timestamp(ts[i]) + td
        vf64 = np.datetime64(_naive(pd.Series([vfrom]))[0])
        ve64 = vf64 + np.timedelta64(1, "D")
        pos = np.searchsorted(mss_ts, vf64, side="left")
        found = None
        for j in range(pos, len(mss)):
            if mss_ts[j] > ve64:
                break
            if mss[j].dir == sdir:
                found = mss[j]; break
        if found is None:
            continue
        opp = [s for s in sw if s.kind == ("L" if sdir > 0 else "H") and s.confirm_ts <= found.confirm_ts]
        if not opp:
            continue
        ssl = opp[-1].price; rref = abs(found.level - ssl)
        if rref <= 0:
            continue
        rows.append((found.confirm_ts, sdir, found.level, ssl, rref))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "entry", "ssl", "rref"])
    _UNIV[key] = u
    return u


def price_s8(mtf, *, k, sl_buf, tp_mode, sides):
    u = universe_s8(mtf, k)
    if len(u) == 0:
        return u
    s = u[u["side"].isin(sides)]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["entry"].values
    sl, tp, risk = _price(side, entry, s["ssl"].values, sl_buf, tp_mode, s["rref"].values)
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S4 — breaker / mitigation zones. Universe = all zones with dir/lo/hi/valid_ts/h4up.
# ============================================================================
def universe_s4(mtf, rule, k, block):
    key = ("s4", rule, k, block)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    z = P.breaker_blocks(sw) if block == "breaker" else P.mitigation_blocks(sw)
    z = z.rename(columns={"valid_ts": "arm_ts"}).copy()
    if len(z):
        z["h4up"] = _h4_up_at(mtf, z["arm_ts"])
    _UNIV[key] = z
    return z


def price_s4(mtf, *, rule, k, block, sl_buf, tp_mode, h4_trend, sides):
    z = universe_s4(mtf, rule, k, block)
    if len(z) == 0:
        return z
    m = z["dir"].isin(sides)
    if h4_trend:
        m &= np.where(z["dir"] > 0, z["h4up"] == 1, z["h4up"] == 0)
    s = z[m]
    if len(s) == 0:
        return s
    side = s["dir"].values.astype(float)
    entry = ((s["lo"] + s["hi"]) / 2).values
    ssl = np.where(side > 0, s["lo"].values, s["hi"].values)
    sl, tp, risk = _price(side, entry, ssl, sl_buf, tp_mode, np.abs(entry - ssl))
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S5 — QML: universe = each MSS with head-zone price + risk scale.
# ============================================================================
def universe_s5(mtf, rule, k):
    key = ("s5", rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    mss = P.mss_events(ev)
    highs = [s for s in sw if s.kind == "H"]
    lows = [s for s in sw if s.kind == "L"]
    rows = []
    for m in mss:
        side = m.dir
        cand = highs if side < 0 else lows
        prev = [s for s in cand if s.confirm_ts <= m.confirm_ts]
        if not prev:
            continue
        head = prev[-1]
        rref = abs(head.price - m.level)
        if rref <= 0:
            continue
        rows.append((m.confirm_ts, side, head.price, rref))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "head", "rref"])
    if len(u):
        u["h4up"] = _h4_up_at(mtf, u["arm_ts"])
    _UNIV[key] = u
    return u


def price_s5(mtf, *, rule, k, sl_buf, tp_mode, h4_trend, sides):
    u = universe_s5(mtf, rule, k)
    if len(u) == 0:
        return u
    m = u["side"].isin(sides)
    if h4_trend:
        m &= np.where(u["side"] > 0, u["h4up"] == 1, u["h4up"] == 0)
    s = u[m]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["head"].values
    sl, tp, risk = _price(side, entry, entry, sl_buf, tp_mode, s["rref"].values)
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S7 — Power of Three: MSS in London after Tokyo-range break. Universe = qualifying
# MSS with tokyo extreme + side.
# ============================================================================
def universe_s7(mtf, k):
    key = ("s7", "15min", k)
    if key in _UNIV:
        return _UNIV[key]
    df = mtf.tf("15min"); tfm = 15
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    mss = P.mss_events(ev)
    ist = df["timestamp"].dt.tz_convert(P.IST)
    dd = df.assign(ist_h=ist.dt.hour + ist.dt.minute/60.0, ist_date=ist.dt.date.astype(str))
    tok = dd[(dd.ist_h >= 5.5) & (dd.ist_h < 14.0)]
    tr = tok.groupby("ist_date").agg(tok_hi=("high", "max"), tok_lo=("low", "min"))
    tok_hi = tr["tok_hi"].to_dict(); tok_lo = tr["tok_lo"].to_dict()
    rows = []
    for m in mss:
        t = pd.Timestamp(m.confirm_ts); t = t.tz_localize("UTC") if t.tz is None else t
        ti = t.tz_convert(P.IST); hh = ti.hour + ti.minute/60.0
        if not (12.5 <= hh < 21.25):
            continue
        d = str(ti.date())
        if d not in tok_hi:
            continue
        side = m.dir
        ssl = tok_lo[d] if side > 0 else tok_hi[d]
        rref = abs(m.level - ssl)
        if rref <= 0:
            continue
        rows.append((m.confirm_ts, side, m.level, ssl, rref))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "entry", "ssl", "rref"])
    _UNIV[key] = u
    return u


def price_s7(mtf, *, k, sl_buf, tp_mode, sides):
    u = universe_s7(mtf, k)
    if len(u) == 0:
        return u
    s = u[u["side"].isin(sides)]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["entry"].values
    sl, tp, risk = _price(side, entry, s["ssl"].values, sl_buf, tp_mode, s["rref"].values)
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S10 — RSI divergence + MSS. Universe = divergence points confirmed by first MSS.
# ============================================================================
def universe_s10(mtf, rule, k, ob_level, os_level):
    key = ("s10", rule, k, ob_level, os_level)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    mss = sorted(P.mss_events(ev), key=lambda e: e.confirm_ts)
    mss_ts = np.array([np.datetime64(_naive(pd.Series([m.confirm_ts]))[0]) for m in mss]) if mss else np.array([], dtype="datetime64[ns]")
    rsi = df["rsi14"].values
    highs = [s for s in sw if s.kind == "H"]; lows = [s for s in sw if s.kind == "L"]
    div = []
    for a, b in zip(highs, highs[1:]):
        if b.price > a.price and rsi[b.idx] < rsi[a.idx] and rsi[a.idx] >= ob_level:
            div.append((-1, b.confirm_ts))
    for a, b in zip(lows, lows[1:]):
        if b.price < a.price and rsi[b.idx] > rsi[a.idx] and rsi[a.idx] <= os_level:
            div.append((1, b.confirm_ts))
    rows = []
    for side, dts in div:
        dts64 = np.datetime64(_naive(pd.Series([dts]))[0])
        pos = np.searchsorted(mss_ts, dts64, side="left")
        # first MSS same dir after divergence
        found = None
        for j in range(pos, len(mss)):
            if mss[j].dir == side:
                found = mss[j]; break
        if found is None:
            continue
        opp = [s for s in sw if s.kind == ("L" if side > 0 else "H") and s.confirm_ts <= found.confirm_ts]
        if not opp:
            continue
        ssl = opp[-1].price; rref = abs(found.level - ssl)
        if rref <= 0:
            continue
        rows.append((found.confirm_ts, side, found.level, ssl, rref))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "entry", "ssl", "rref"])
    _UNIV[key] = u
    return u


def price_s10(mtf, *, rule, k, ob_level, os_level, sl_buf, tp_mode, sides):
    u = universe_s10(mtf, rule, k, ob_level, os_level)
    if len(u) == 0:
        return u
    s = u[u["side"].isin(sides)]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["entry"].values
    sl, tp, risk = _price(side, entry, s["ssl"].values, sl_buf, tp_mode, s["rref"].values)
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S11 — Fib retracement of swing legs + EMA confluence. Universe = legs with fib-ready
# geometry + ema-align flag (per fib applied at price time; universe holds leg + ema).
# ============================================================================
def universe_s11(mtf, rule, k):
    key = ("s11", rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    e50 = df["ema50"].values; e100 = df["ema100"].values
    rows = []
    for a, b in zip(sw, sw[1:]):
        if a.kind == "L" and b.kind == "H" and b.price > a.price:
            rows.append((b.confirm_ts, 1, a.price, b.price, int(e50[b.idx] > e100[b.idx])))
        elif a.kind == "H" and b.kind == "L" and b.price < a.price:
            rows.append((b.confirm_ts, -1, b.price, a.price, int(e50[b.idx] < e100[b.idx])))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "lo", "hi", "ema_ok"])
    _UNIV[key] = u
    return u


def price_s11(mtf, *, rule, k, fib, sl_buf, tp_mode, ema_confirm, sides):
    u = universe_s11(mtf, rule, k)
    if len(u) == 0:
        return u
    m = u["side"].isin(sides)
    if ema_confirm:
        m &= u["ema_ok"] == 1
    s = u[m]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    rng = (s["hi"] - s["lo"]).values
    entry = np.where(side > 0, s["hi"].values - fib * rng, s["lo"].values + fib * rng)
    ssl = np.where(side > 0, s["lo"].values, s["hi"].values)
    sl, tp, risk = _price(side, entry, ssl, sl_buf, tp_mode, np.abs(entry - ssl))
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


# ============================================================================
# S12 — fake-breakout filtered. Universe = all structure breaks with vol/rsi/h4 meta.
# ============================================================================
def universe_s12(mtf, rule, k):
    key = ("s12", rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = _TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    vol = df["volume"].values; rsi = df["rsi14"].values; close = df["close"].values
    volma = pd.Series(vol).rolling(20).mean().values
    rows = []
    for e in ev:
        j = e.break_idx
        vr = vol[j] / volma[j] if np.isfinite(volma[j]) and volma[j] > 0 else 0.0
        rows.append((e.confirm_ts, e.dir, close[j], e.level, vr, rsi[j]))
    u = pd.DataFrame(rows, columns=["arm_ts", "side", "entry", "ssl", "vol_ratio", "rsi"])
    if len(u):
        u["h4up"] = _h4_up_at(mtf, u["arm_ts"])
    _UNIV[key] = u
    return u


def price_s12(mtf, *, rule, k, vol_mult, use_rsi, h4_trend, sl_buf, tp_mode, sides):
    u = universe_s12(mtf, rule, k)
    if len(u) == 0:
        return u
    m = u["side"].isin(sides) & (u["vol_ratio"] >= vol_mult)
    if use_rsi:
        m &= ~((u["side"] > 0) & (u["rsi"] > 75))
        m &= ~((u["side"] < 0) & (u["rsi"] < 25))
    if h4_trend:
        m &= np.where(u["side"] > 0, u["h4up"] == 1, u["h4up"] == 0)
    s = u[m]
    if len(s) == 0:
        return s
    side = s["side"].values.astype(float)
    entry = s["entry"].values
    rref = np.abs(entry - s["ssl"].values)
    sl, tp, risk = _price(side, entry, s["ssl"].values, sl_buf, tp_mode, rref)
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})
