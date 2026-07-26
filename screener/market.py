"""Weinstein macro timing gauges: where are we in the cycle?

Everything here is computed from the weekly bars we already download, so no
extra data source is needed. Components follow Weinstein's own market-timing
chapter, including his asymmetry note: the A/D line tops out BEFORE the index
but does NOT bottom before it — so A/D divergence only ever scores negative.

IMPORTANT framing: this tab is mean-reverting (cycle position), while the rest
of the screener is trend-following (entries). They will disagree, and that is
by design. Weinstein used the macro read for EXPOSURE SIZING, not for entries.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


# --------------------------------------------------------------------------
# stage classification (quadrant of price vs. MA and MA slope)
# --------------------------------------------------------------------------
def classify_stage(close: float, sma: float, slope: float,
                   flat: float = 0.005) -> int:
    if not (np.isfinite(close) and np.isfinite(sma) and np.isfinite(slope)):
        return 0
    if close > sma:
        return 2 if slope > flat else 3
    return 4 if slope < -flat else 1


STAGE_NAME = {1: "Stage 1 (Basis)", 2: "Stage 2 (Aufwärts)",
              3: "Stage 3 (Topping)", 4: "Stage 4 (Abwärts)", 0: "n/a"}


def _closes_frame(weekly: dict[str, pd.DataFrame],
                  tickers: list[str]) -> pd.DataFrame:
    cols = {t: weekly[t]["close"] for t in tickers if t in weekly}
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


# --------------------------------------------------------------------------
# breadth primitives
# --------------------------------------------------------------------------
def ad_line(px: pd.DataFrame) -> pd.Series:
    """Cumulative weekly advances minus declines across the universe."""
    chg = px.diff()
    adv = (chg > 0).sum(axis=1)
    dec = (chg < 0).sum(axis=1)
    return (adv - dec).cumsum()


def new_high_low(px: pd.DataFrame, window: int = 52) -> pd.DataFrame:
    """Weekly count of new `window`-week highs and lows, and the net
    differential as a share of the universe."""
    roll_max = px.rolling(window).max()
    roll_min = px.rolling(window).min()
    nh = (px >= roll_max * 0.9999).sum(axis=1)
    nl = (px <= roll_min * 1.0001).sum(axis=1)
    n = px.notna().sum(axis=1).replace(0, np.nan)
    return pd.DataFrame({"nh": nh, "nl": nl,
                         "net_pct": (nh - nl) / n * 100.0})


def pct_above_ma(px: pd.DataFrame, weeks: int = C.MA_WEEKS) -> pd.Series:
    sma = px.rolling(weeks).mean()
    above = (px > sma).sum(axis=1)
    n = (px.notna() & sma.notna()).sum(axis=1).replace(0, np.nan)
    return above / n * 100.0


def stage_distribution(weekly: dict[str, pd.DataFrame],
                       tickers: list[str]) -> dict:
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for t in tickers:
        wk = weekly.get(t)
        if wk is None or len(wk) < C.MA_WEEKS + C.SLOPE_LOOKBACK + 1:
            continue
        close = wk["close"]
        sma = close.rolling(C.MA_WEEKS).mean()
        sl = I.sma_slope(sma)
        st = classify_stage(float(close.iloc[-1]), float(sma.iloc[-1]),
                            float(sl.iloc[-1]))
        if st in counts:
            counts[st] += 1
    total = sum(counts.values()) or 1
    return {"counts": counts, "total": total,
            "pct": {k: round(v / total * 100, 1) for k, v in counts.items()}}


# --------------------------------------------------------------------------
# divergence detection
# --------------------------------------------------------------------------
def _weeks_since_max(s: pd.Series, window: int) -> int:
    w = s.iloc[-window:].dropna()
    if len(w) < 3:
        return 999
    return int(len(w) - 1 - int(np.argmax(w.values)))


def _weeks_since_min(s: pd.Series, window: int) -> int:
    w = s.iloc[-window:].dropna()
    if len(w) < 3:
        return 999
    return int(len(w) - 1 - int(np.argmin(w.values)))


def ad_divergence(index_close: pd.Series, ad: pd.Series,
                  window: int = 52, fresh: int = 13) -> dict:
    """Top warning only: index printed a recent high, A/D line did not.
    Weinstein: the A/D line leads at tops but lags at bottoms, so this is
    never read as a bottom signal."""
    idx_age = _weeks_since_max(index_close, window)
    ad_age = _weeks_since_max(ad, window)
    diverging = bool(idx_age <= fresh and ad_age > fresh)
    return {"index_high_age": idx_age, "ad_high_age": ad_age,
            "divergence": diverging}


def hl_divergence(index_close: pd.Series, hl: pd.DataFrame,
                  fresh: int = 13) -> dict:
    """Index near its 52w high while the net high/low differential is
    negative = classic distribution reading."""
    hi52 = index_close.iloc[-52:].max()
    near_high = bool(index_close.iloc[-1] >= hi52 * 0.95)
    net = float(hl["net_pct"].iloc[-4:].mean())
    return {"near_high": near_high, "net_pct_4w": round(net, 2),
            "top_divergence": bool(near_high and net < 0),
            "washout": bool(not near_high and net < -10)}


# --------------------------------------------------------------------------
# 4-month rule on the heavyweights
# --------------------------------------------------------------------------
def four_month_rule(weekly: dict[str, pd.DataFrame], tickers: list[str],
                    top_n: int = 50, weeks: int = 17) -> dict:
    """Weinstein: a big stock that has made no new high (in an uptrend) or no
    new low (in a downtrend) for four months is probably reversing.

    'Big' is proxied by median weekly dollar volume — we have no market-cap
    feed in the pipeline, so this is a liquidity proxy, not a size ranking.
    """
    liq = []
    for t in tickers:
        wk = weekly.get(t)
        if wk is None or len(wk) < 60:
            continue
        dv = float((wk["close"] * wk["volume"]).iloc[-52:].median())
        if np.isfinite(dv):
            liq.append((dv, t))
    liq.sort(reverse=True)
    big = [t for _, t in liq[:top_n]]

    up_stall, down_stall, rows = [], [], []
    for t in big:
        wk = weekly[t]
        close = wk["close"]
        sma = close.rolling(C.MA_WEEKS).mean()
        sl = I.sma_slope(sma)
        st = classify_stage(float(close.iloc[-1]), float(sma.iloc[-1]),
                            float(sl.iloc[-1]))
        age_high = _weeks_since_max(close, 52)
        age_low = _weeks_since_min(close, 52)
        # Weinstein, literally: NEITHER a new high NOR a new low in four
        # months -> the stock has gone sideways -> prior trend is ending.
        stalling, age = None, 0
        if age_high >= weeks and age_low >= weeks:
            age = min(age_high, age_low)
            if st in (2, 3):
                stalling = "Aufwärtstrend ohne neues Hoch"
                up_stall.append(t)
            else:
                stalling = "Abwärtstrend ohne neues Tief"
                down_stall.append(t)
        if stalling:
            rows.append({"ticker": t, "stage": STAGE_NAME[st],
                         "note": stalling, "weeks_since_high": age})
    rows.sort(key=lambda r: -r["weeks_since_high"])
    n = len(big) or 1
    return {"universe": n, "up_stall_pct": round(len(up_stall) / n * 100, 1),
            "down_stall_pct": round(len(down_stall) / n * 100, 1),
            "rows": rows[:25]}


# --------------------------------------------------------------------------
# world markets
# --------------------------------------------------------------------------
def world_markets(weekly: dict[str, pd.DataFrame],
                  spx_close: pd.Series) -> list[dict]:
    rows = []
    for sym, name in C.WORLD_INDICES.items():
        wk = weekly.get(sym)
        if wk is None or len(wk) < C.MA_WEEKS + C.SLOPE_LOOKBACK + 1:
            continue
        close = wk["close"]
        sma = close.rolling(C.MA_WEEKS).mean()
        sl = I.sma_slope(sma)
        st = classify_stage(float(close.iloc[-1]), float(sma.iloc[-1]),
                            float(sl.iloc[-1]))
        mrs = I.mansfield_rs(close, spx_close)
        rows.append({
            "symbol": sym, "name": name, "stage": st,
            "stage_name": STAGE_NAME[st],
            "vs_ma": round(float(close.iloc[-1] / sma.iloc[-1] - 1) * 100, 1),
            "slope": round(float(sl.iloc[-1]) * 100, 2),
            "mrs": round(float(mrs.iloc[-1]), 1)
            if np.isfinite(mrs.iloc[-1]) else None,
            "spark": [round(float(v), 3) for v in close.iloc[-52:]],
        })
    return sorted(rows, key=lambda r: r["stage"])


# --------------------------------------------------------------------------
# price / dividend ratio (display only — see caveat in the dashboard)
# --------------------------------------------------------------------------
def price_dividend(weekly: dict[str, pd.DataFrame]) -> dict | None:
    """SPY trailing-12m distributions as a stand-in for the index dividend.
    Weinstein's absolute thresholds (<15 cheap, >26 expensive) have been
    structurally broken since buybacks replaced dividends, so the percentile
    against its own history is the only usable reading."""
    try:
        import yfinance as yf
        div = yf.Ticker("SPY").dividends
        if div is None or len(div) < 8:
            return None
        div.index = pd.to_datetime(div.index).tz_localize(None)
        spy = weekly.get("SPY")
        if spy is None or len(spy) < 60:
            return None
        px = spy["close"]
        ttm = div.rolling("365D").sum()
        ttm = ttm.reindex(px.index, method="ffill").dropna()
        pd_ratio = (px.reindex(ttm.index) / ttm).replace(
            [np.inf, -np.inf], np.nan).dropna()
        if len(pd_ratio) < 40:
            return None
        cur = float(pd_ratio.iloc[-1])
        pct = float((pd_ratio <= cur).mean() * 100)
        return {"ratio": round(cur, 1),
                "yield_pct": round(100.0 / cur, 2),
                "percentile": round(pct, 0),
                "spark": [round(float(v), 2) for v in pd_ratio.iloc[-156:]]}
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# composite
# --------------------------------------------------------------------------
def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def breadth_score(pct: float, near_high: bool) -> float:
    """Breadth is context-dependent, not simply mean-reverting.

    Weinstein reads broad participation as HEALTHY; the top signal is
    narrowing leadership WHILE the index still makes highs. Away from the
    highs the same weak reading means washout instead.

        index near high + weak breadth  -> narrow leadership = top
        index near high + broad breadth -> healthy = neutral (late only >85%)
        index off high  + weak breadth  -> washout = bottom
        index off high  + broad breadth -> recovering = mildly bottom
    """
    if near_high:
        if pct < 50.0:
            return _clip(-(50.0 - pct) / 30.0)
        return -_clip(max(pct - 85.0, 0.0) / 15.0) * 0.4
    if pct < 30.0:
        return _clip((30.0 - pct) / 25.0)
    return _clip((50.0 - pct) / 60.0) * 0.5


def compute(weekly: dict[str, pd.DataFrame], universe: pd.DataFrame,
            benches: dict[str, pd.Series]) -> dict:
    """Returns everything the MARKTLAGE tab needs."""
    us = [t for t, u in zip(universe["ticker"], universe["universe"])
          if u in ("SPX", "NDX") and t in weekly]
    eu = [t for t, u in zip(universe["ticker"], universe["universe"])
          if u == "SXXP" and t in weekly]

    spx = benches.get(C.BENCH_US)
    px_us = _closes_frame(weekly, us)
    px_eu = _closes_frame(weekly, eu)

    ad = ad_line(px_us)
    hl = new_high_low(px_us)
    above = pct_above_ma(px_us)
    dist = stage_distribution(weekly, us)

    sma_spx = spx.rolling(C.MA_WEEKS).mean()
    slope_spx = I.sma_slope(sma_spx)
    spx_stage = classify_stage(float(spx.iloc[-1]), float(sma_spx.iloc[-1]),
                               float(slope_spx.iloc[-1]))

    adiv = ad_divergence(spx, ad)
    hdiv = hl_divergence(spx, hl)
    fmr = four_month_rule(weekly, us)
    world = world_markets(weekly, spx)
    pdr = price_dividend(weekly)

    # ---- component scores: +1 = closer to a bottom, -1 = closer to a top ---
    comps = []
    near_high = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
    ctx = "Index nahe 52W-Hoch" if near_high else "Index fern vom 52W-Hoch"

    # Stage 2 says nothing about proximity to a top — tops FORM out of it.
    s_stage = {1: 1.0, 2: 0.2, 3: -1.0, 4: -0.4}.get(spx_stage, 0.0)
    comps.append({"key": "Index-Stage (S&P 500)",
                  "value": STAGE_NAME[spx_stage],
                  "detail": f"{float(spx.iloc[-1] / sma_spx.iloc[-1] - 1) * 100:+.1f}% "
                            f"zum 30W-MA · Slope {float(slope_spx.iloc[-1]) * 100:+.2f}%",
                  "score": s_stage, "weight": 0.20})

    pa = float(above.iloc[-1])
    s_above = breadth_score(pa, near_high)
    comps.append({"key": "% über 30W-MA (US)", "value": f"{pa:.0f}%",
                  "detail": f"{ctx} — " + (
                      "schmale Führung bei hohem Index = Distribution"
                      if near_high and pa < 50 else
                      "breite Beteiligung, gesund"
                      if near_high else
                      "Auswaschung: kaum ein Titel über dem MA"
                      if pa < 30 else "Erholung der Breite unter dem Hoch"),
                  "score": s_above, "weight": 0.15})

    net_stage = dist["pct"][2] - dist["pct"][4]
    s_dist = breadth_score((net_stage + 100.0) / 2.0, near_high)
    comps.append({"key": "Stage-Verteilung (S2 − S4)",
                  "value": f"{net_stage:+.0f} Pp",
                  "detail": f"S1 {dist['pct'][1]}% · S2 {dist['pct'][2]}% · "
                            f"S3 {dist['pct'][3]}% · S4 {dist['pct'][4]}%",
                  "score": s_dist, "weight": 0.15})

    s_ad = -1.0 if adiv["divergence"] else 0.0
    comps.append({"key": "A/D-Divergenz (nur Top-Signal)",
                  "value": "Divergenz" if adiv["divergence"] else "keine",
                  "detail": f"Index-Hoch vor {adiv['index_high_age']}W · "
                            f"A/D-Hoch vor {adiv['ad_high_age']}W — laut "
                            f"Weinstein am Boden wertlos, daher nie positiv",
                  "score": s_ad, "weight": 0.15})

    if hdiv["top_divergence"]:
        s_hl = -1.0                       # index at highs, breadth negative
    elif hdiv["washout"]:
        s_hl = 0.7                        # many new lows far from the high
    elif near_high:
        s_hl = 0.0                        # expanding new highs = healthy
    else:
        s_hl = _clip(hdiv["net_pct_4w"] / 20.0) * 0.5   # recovering off a low
    comps.append({"key": "High-Low-Differential",
                  "value": f"{hdiv['net_pct_4w']:+.1f}% (4W-Ø)",
                  "detail": ("Top-Divergenz: Index nahe Hoch, Differential negativ"
                             if hdiv["top_divergence"] else
                             "Auswaschung: viele neue Tiefs fern vom Hoch"
                             if hdiv["washout"] else "unauffällig"),
                  "score": s_hl, "weight": 0.20})

    if world:
        w_bull = sum(1 for r in world if r["stage"] == 2) / len(world)
        w_bear = sum(1 for r in world if r["stage"] == 4) / len(world)
        us_bull = 1.0 if spx_stage == 2 else 0.0
        s_world = _clip((w_bear - w_bull) + (us_bull - (1 - w_bear)) * 0.5)
        detail = (f"{sum(1 for r in world if r['stage'] == 2)}/{len(world)} "
                  f"Indizes in Stage 2 · "
                  f"{sum(1 for r in world if r['stage'] == 4)} in Stage 4")
    else:
        s_world, detail = 0.0, "keine Daten"
    comps.append({"key": "Weltmärkte (Frühindikator)",
                  "value": detail.split(" · ")[0], "detail": detail,
                  "score": s_world, "weight": 0.10})

    s_fmr = _clip((fmr["up_stall_pct"] - fmr["down_stall_pct"]) / 40.0 * -1)
    comps.append({"key": "4-Monats-Regel (Schwergewichte)",
                  "value": f"{fmr['up_stall_pct']:.0f}% stockend",
                  "detail": f"{fmr['up_stall_pct']:.0f}% der Top-50 im Aufwärtstrend "
                            f"ohne neues Hoch · {fmr['down_stall_pct']:.0f}% im "
                            f"Abwärtstrend ohne neues Tief",
                  "score": s_fmr, "weight": 0.05})

    total_w = sum(c["weight"] for c in comps)
    score = sum(c["score"] * c["weight"] for c in comps) / total_w * 100.0
    for c in comps:
        c["contribution"] = round(c["score"] * c["weight"] / total_w * 100, 1)
        c["score"] = round(c["score"], 2)

    if score >= 40:
        label = "deutlich näher am Boden"
    elif score >= 15:
        label = "eher Boden-Seite"
    elif score > -15:
        label = "neutral / Zyklusmitte"
    elif score > -40:
        label = "eher Top-Seite"
    else:
        label = "deutlich näher am Top"

    return {
        "score": round(score, 1), "label": label,
        "components": comps,
        "stage_dist": dist,
        "spark_spx": [round(float(v), 2) for v in spx.iloc[-104:]],
        "spark_ad": [round(float(v), 1) for v in ad.iloc[-104:]],
        "spark_hl": [round(float(v), 2) for v in hl["net_pct"].iloc[-104:]],
        "spark_above": [round(float(v), 1) for v in above.iloc[-104:]],
        "world": world,
        "four_month": fmr,
        "price_dividend": pdr,
        "breadth_universe": len(us),
        "eu_breadth": (round(float(pct_above_ma(px_eu).iloc[-1]), 0)
                       if len(px_eu.columns) > 50 else None),
    }
