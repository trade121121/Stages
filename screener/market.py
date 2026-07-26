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


def pct_rank(s: pd.Series) -> float:
    """Percentile of the latest value within the series' own history.
    Absolute breadth thresholds are meaningless without this context."""
    s = s.dropna()
    if len(s) < 30:
        return 50.0
    return float((s <= s.iloc[-1]).mean() * 100.0)


def z_change(s: pd.Series, weeks: int = 26) -> float:
    """z-score of the latest n-week change against its own distribution."""
    d = s.diff(weeks).dropna()
    if len(d) < 30 or float(d.std()) == 0.0:
        return 0.0
    return float((d.iloc[-1] - d.mean()) / d.std())


def norm_change(s: pd.Series, span: float, weeks: int = 26) -> float:
    """n-week change of a series, normalised to roughly [-1, +1] by an
    explicit, interpretable span (e.g. 25 percentage points of breadth)."""
    d = s.diff(weeks).dropna()
    if d.empty:
        return 0.0
    return _clip(float(d.iloc[-1]) / span)


def divergence(breadth_norm: float, index_chg_26w: float,
               index_span: float = 0.15, cap_pos: float = 0.3) -> float:
    """Breadth momentum minus index momentum, both normalised to [-1, +1].

    Direct and unit-free rather than percentile- or z-based: percentiles
    degenerate on trending series, z-scores explode on near-constant ones.
    Negative = breadth lagging a rising index (top warning). Positive is
    capped — Weinstein: breadth does not lead at bottoms.
    """
    i = _clip(index_chg_26w / index_span)
    return _clip((breadth_norm - i) / 2.0, -1.0, cap_pos)


def one_sided(value: float, midpoint: float, span: float,
              near_high: bool, invert: bool = False) -> float:
    """Level term around a NATURAL midpoint, with the sign set by context.

        index near its high  -> only weakness speaks (narrow leadership = top)
        index far from high  -> only weakness speaks (washout = bottom)

    Strength never generates a signal in either regime: a healthy market is
    supposed to be silent. `invert=True` for series where HIGH means weak
    (e.g. the share of stocks in Stage 3+4).
    """
    d = (value - midpoint) / span
    if invert:
        d = -d
    return _clip(min(0.0, d)) if near_high else _clip(max(0.0, -d))


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
    # Every continuous gauge is scored as PERCENTILE against its own history
    # plus a DIVERGENCE term against the index. No absolute thresholds, no
    # dead zones: each component must be able to speak in normal conditions.
    comps = []
    near_high = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
    hist_weeks = int(above.dropna().shape[0])

    # 1) Index stage, modulated by how extended the index is vs. its own MA
    ext = spx / sma_spx - 1.0
    ext_p = pct_rank(ext)
    s_stage = _clip({1: 1.0, 2: 0.2, 3: -1.0, 4: -0.4}.get(spx_stage, 0.0)
                    - max(0.0, (ext_p - 50.0) / 50.0) * 0.4)
    comps.append({"key": "Index-Stage (S&P 500)",
                  "value": STAGE_NAME[spx_stage],
                  "detail": f"{float(ext.iloc[-1]) * 100:+.1f}% zum 30W-MA "
                            f"({ext_p:.0f}. Perzentil) · Slope "
                            f"{float(slope_spx.iloc[-1]) * 100:+.2f}%",
                  "score": s_stage, "weight": 0.20})

    # 2) Breadth: level percentile (mild) + divergence vs. index (dominant)
    pa = float(above.iloc[-1])
    pa_p = pct_rank(above)
    idx_chg = float(spx.pct_change(26).iloc[-1])
    lvl = one_sided(pa, 50.0, 40.0, near_high)
    div_b = divergence(norm_change(above.rolling(4).mean(), 25.0), idx_chg)
    s_above = _clip(0.4 * lvl + 0.6 * div_b)
    comps.append({"key": "% über 30W-MA (US)",
                  "value": f"{pa:.0f}% · {pa_p:.0f}. Pz",
                  "detail": f"Niveau {lvl:+.2f} (Mitte 50%) · Divergenz "
                            f"{div_b:+.2f} — 26W-Momentum der Breite vs. Index, "
                            f"Perzentilvergleich",
                  "score": s_above, "weight": 0.20})

    # 3) Topping share (S3+S4) — kept light, overlaps with (2)
    top_share = dist["pct"][3] + dist["pct"][4]
    # same context rule: many stocks already broken WHILE the index sits at
    # its high = narrow leadership; the same reading after a decline = washout
    s_dist = one_sided(top_share, 50.0, 40.0, near_high, invert=True)
    comps.append({"key": "Anteil S3+S4 (Topping/Abwärts)",
                  "value": f"{top_share:.0f}%",
                  "detail": f"S1 {dist['pct'][1]}% · S2 {dist['pct'][2]}% · "
                            f"S3 {dist['pct'][3]}% · S4 {dist['pct'][4]}% "
                            f"— {'Index nahe Hoch: hoher Anteil = schmale Führung'
                                  if near_high else 'Index fern vom Hoch: hoher Anteil = Auswaschung'}",
                  "score": s_dist, "weight": 0.10})

    # 4) A/D line: continuous divergence, positives capped (Weinstein)
    n_stocks = max(int(px_us.notna().sum(axis=1).iloc[-1]), 1)
    ad_norm = _clip(float(ad.diff(26).iloc[-1]) / (n_stocks * 26 * 0.15))
    s_ad = divergence(ad_norm, idx_chg)
    comps.append({"key": "A/D-Linie vs. Index",
                  "value": f"{ad_norm:+.2f} vs Index {_clip(idx_chg/0.15):+.2f}",
                  "detail": f"26W-Momentum der A/D-Linie im Perzentilvergleich "
                            f"zum Index · Index-Hoch vor "
                            f"{adiv['index_high_age']}W, A/D-Hoch vor "
                            f"{adiv['ad_high_age']}W · positive Werte gedeckelt, "
                            f"da die A/D-Linie am Boden nicht vorläuft",
                  "score": s_ad, "weight": 0.15})

    # 5) High/Low differential: percentile + divergence
    hl_net = hl["net_pct"].rolling(4).mean()
    hl_p = pct_rank(hl_net)
    lvl_hl = one_sided(float(hl_net.iloc[-1]), 0.0, 15.0, near_high)
    div_hl = divergence(norm_change(hl_net, 25.0), idx_chg)
    s_hl = _clip(0.4 * lvl_hl + 0.6 * div_hl)
    if hdiv["washout"]:
        s_hl = _clip(max(s_hl, 0.6))          # many new lows far from the high
    comps.append({"key": "High-Low-Differential",
                  "value": f"{hdiv['net_pct_4w']:+.1f}% · {hl_p:.0f}. Pz",
                  "detail": ("Auswaschung: viele neue Tiefs fern vom Hoch · "
                             if hdiv["washout"] else "") +
                            f"Niveau {lvl_hl:+.2f} (Nulllinie) · Divergenz "
                            f"{div_hl:+.2f}",
                  "score": s_hl, "weight": 0.20})

    # 6) World markets — Weinstein: foreign markets often turn FIRST, so the
    #    signal is the divergence between them and the US, not their level.
    ex_us = [r for r in world if r["symbol"] not in ("^GSPC", "^IXIC", "^RUT")]
    if ex_us:
        n_w = len(ex_us)
        sh2 = sum(1 for r in ex_us if r["stage"] == 2) / n_w
        sh4 = sum(1 for r in ex_us if r["stage"] == 4) / n_w
        if spx_stage in (2, 3):          # US still up -> foreign weakness warns
            s_world = -_clip((sh4 - 0.15) / 0.5)
            note = "US im Aufwärtstrend — Ausland bricht weg?"
        else:                            # US already down -> foreign strength leads
            s_world = _clip((sh2 - 0.15) / 0.5)
            note = "US im Abwärtstrend — dreht das Ausland zuerst?"
        detail = (f"{note} · {int(sh2 * n_w)}/{n_w} ex-US in Stage 2, "
                  f"{int(sh4 * n_w)} in Stage 4")
    else:
        s_world, detail = 0.0, "keine Auslandsdaten"
    comps.append({"key": "Weltmärkte (Frühindikator)",
                  "value": f"{s_world:+.2f}", "detail": detail,
                  "score": s_world, "weight": 0.10})

    # 7) Four-month rule
    s_fmr = _clip((fmr["down_stall_pct"] - fmr["up_stall_pct"]) / 30.0)
    comps.append({"key": "4-Monats-Regel (Schwergewichte)",
                  "value": f"{fmr['up_stall_pct']:.0f}% / "
                           f"{fmr['down_stall_pct']:.0f}%",
                  "detail": f"{fmr['up_stall_pct']:.0f}% der Top-50 im "
                            f"Aufwärtstrend ohne neues Hoch · "
                            f"{fmr['down_stall_pct']:.0f}% im Abwärtstrend "
                            f"ohne neues Tief",
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
        "hist_weeks": hist_weeks,
        "near_high": near_high,
        "eu_breadth": (round(float(pct_above_ma(px_eu).iloc[-1]), 0)
                       if len(px_eu.columns) > 50 else None),
    }


# --------------------------------------------------------------------------
# score history — a single reading says little, the trajectory says a lot
# --------------------------------------------------------------------------
def log_history(macro: dict, path: str) -> list[dict]:
    """Append this run's score to a CSV and return the full series.
    Written into docs/ so the existing workflow commits it automatically."""
    import csv
    import os
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = {"date": today, "score": macro["score"]}
    for c in macro["components"]:
        row[c["key"]] = c["score"]

    rows: list[dict] = []
    if os.path.exists(path):
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("date") != today]
        except Exception:  # noqa: BLE001
            rows = []
    rows.append({k: str(v) for k, v in row.items()})
    rows.sort(key=lambda r: r["date"])

    fields = ["date", "score"] + [c["key"] for c in macro["components"]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    out = []
    for r in rows:
        try:
            out.append({"date": r["date"], "score": float(r["score"])})
        except (ValueError, KeyError):
            continue
    return out
