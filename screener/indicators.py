"""Weekly indicators: 30W SMA, slope, Mansfield Relative Strength, base metrics.

All functions operate on weekly OHLCV DataFrames indexed by week-end date
with columns: open, high, low, close, volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly (Friday-anchored) bars."""
    out = pd.DataFrame({
        "open": df["open"].resample("W-FRI").first(),
        "high": df["high"].resample("W-FRI").max(),
        "low": df["low"].resample("W-FRI").min(),
        "close": df["close"].resample("W-FRI").last(),
        "volume": df["volume"].resample("W-FRI").sum(),
    })
    return out.dropna(subset=["close"])


def mansfield_rs(close: pd.Series, bench_close: pd.Series,
                 weeks: int = C.MRS_WEEKS) -> pd.Series:
    """Mansfield Relative Strength: ((RP / SMA_n(RP)) - 1) * 100."""
    bench = bench_close.reindex(close.index).ffill()
    rp = close / bench
    return (rp / rp.rolling(weeks).mean() - 1.0) * 100.0


def sma_slope(sma: pd.Series, lookback: int = C.SLOPE_LOOKBACK) -> pd.Series:
    """Relative slope of the SMA vs. `lookback` weeks ago."""
    return sma / sma.shift(lookback) - 1.0


def weeks_since_52w_low(close: pd.Series) -> int:
    """Weeks elapsed since the 52-week closing low (as of last bar)."""
    window = close.iloc[-52:]
    return int(len(window) - 1 - int(np.argmin(window.values)))


def ma_crossings(close: pd.Series, sma: pd.Series, window: int = 26) -> int:
    """Number of price/SMA sign changes over the trailing window."""
    diff = (close - sma).iloc[-window:].dropna()
    if len(diff) < 2:
        return 0
    signs = np.sign(diff.values)
    signs[signs == 0] = 1
    return int((np.diff(signs) != 0).sum())


def ma_was_flat(slope: pd.Series,
                lookback: int = C.LONG_FLAT_LOOKBACK,
                threshold: float = C.LONG_FLAT_SLOPE_ABS) -> bool:
    """True if the MA slope was near zero at some point in the recent window."""
    recent = slope.iloc[-lookback:].dropna()
    if recent.empty:
        return False
    return bool((recent.abs() < threshold).any())


def fresh_cross_up(mrs: pd.Series, weeks: int = C.MRS_FRESH_CROSS_WEEKS) -> bool:
    """MRS crossed above zero within the last `weeks` bars."""
    m = mrs.dropna()
    if len(m) < weeks + 1:
        return False
    window = m.iloc[-(weeks + 1):]
    return bool(window.iloc[-1] > 0 and (window.iloc[:-1] <= 0).any())


def volume_ratio(volume: pd.Series, avg_weeks: int = C.VOL_AVG_WEEKS) -> float:
    """Current week's volume vs. trailing average (excluding current week)."""
    base = volume.shift(1).rolling(avg_weeks).mean().iloc[-1]
    if not np.isfinite(base) or base <= 0:
        return np.nan
    return float(volume.iloc[-1] / base)


def base_volatility(close: pd.Series, window: int = 26) -> float:
    """Range of the trailing base (max/min - 1). Volatile bases score HIGHER
    (Weinstein: wilder bases often precede stronger Stage-2 moves)."""
    w = close.iloc[-(window + 1):-1]
    if len(w) < 5 or w.min() <= 0:
        return np.nan
    return float(w.max() / w.min() - 1.0)


def prior_markup(close: pd.Series, sma: pd.Series | None = None,
                 factor: float = C.SHORT_MIN_PRIOR_MARKUP) -> bool:
    """Did a genuine Stage-2 markup precede the current weakness?

    Ratio alone is not enough: a stock oscillating in a wide range clears
    1.5x from range low to range high without ever having trended. A real
    markup also (a) takes time and (b) keeps price above a rising 30W MA for
    most of its duration. Both are checked when `sma` is supplied."""
    lb = min(len(close), C.SHORT_MARKUP_LOOKBACK)
    if lb < 60:
        return False
    win = close.iloc[-lb:]
    v = win.values
    i_max = int(np.argmax(v))
    if i_max < 4:                       # high sits at the very start: no markup
        return False
    i_low = int(np.argmin(v[:i_max]))
    low, high = float(v[i_low]), float(v[i_max])
    if low <= 0 or high / low < factor:
        return False
    if i_max - i_low < C.SHORT_MARKUP_MIN_WEEKS:      # spike, not a markup
        return False
    # New ground: within a range, an up-leg looks exactly like a markup — same
    # slope, same time above the MA. The difference is that the range high is a
    # level the stock has traded at before, while a markup high is not.
    if i_low >= 10:
        prior_high = float(v[:i_low].max())
        if prior_high > 0 and high / prior_high < C.SHORT_MARKUP_NEW_GROUND:
            return False
    if sma is not None:
        seg_c = win.iloc[i_low:i_max + 1]
        seg_s = sma.iloc[-lb:].iloc[i_low:i_max + 1]
        ok = seg_s.notna()
        if int(ok.sum()) >= 10:
            above = float((seg_c[ok] > seg_s[ok]).mean())
            if above < C.SHORT_MARKUP_MIN_ABOVE_MA:   # range, not a trend
                return False
    return True


def bearish_divergence(close: pd.Series, mrs: pd.Series) -> bool:
    """Price printed a 52w high within the last 26 weeks while current MRS < 0:
    relative strength broke before price."""
    if len(close) < 52 or mrs.dropna().empty:
        return False
    high_52w = close.iloc[-52:].max()
    recent_high = close.iloc[-26:].max()
    return bool(recent_high >= high_52w * 0.999 and mrs.iloc[-1] < 0)


def markup_retrace(close: pd.Series,
                   lookback: int = C.SHORT_MARKUP_LOOKBACK) -> float:
    """Fraction of the prior Stage-2 markup already retraced, in log space.

    0.0 = still at the high, 1.0 = the entire markup has been given back.
    Log space keeps the measure meaningful for multi-baggers: a 40x runner
    that halved has retraced far less of its move than a 1.6x runner that
    halved, even though both are "50% off the high".
    """
    lb = min(len(close), lookback)
    if lb < 60:
        return 1.0
    w = close.iloc[-lb:].values
    i_max = int(np.argmax(w))
    if i_max < 4:
        return 1.0
    low_before = float(w[:i_max].min())
    high = float(w[i_max])
    cur = float(w[-1])
    if low_before <= 0 or cur <= 0 or high <= low_before:
        return 1.0
    return float(np.log(high / cur) / np.log(high / low_before))


def atr_pct(weekly: pd.DataFrame, weeks: int = 26) -> float:
    """Average weekly true range as a share of price.

    Zones (buy/short bands around the 30W MA) must scale with a stock's own
    noise: 8% is a wide band for a utility and pure noise for a 15%-ATR miner.
    """
    h, l, c = weekly["high"], weekly["low"], weekly["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    a = tr.rolling(weeks).mean().iloc[-1]
    px = float(c.iloc[-1])
    if not np.isfinite(a) or px <= 0:
        return float("nan")
    return float(a) / px


def zone_width(atr: float, mult: float, lo: float, hi: float) -> float:
    """Volatility-scaled zone width, clamped to a sane range."""
    if not np.isfinite(atr):
        return lo
    return float(min(max(atr * mult, lo), hi))
