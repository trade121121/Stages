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


def prior_markup(close: pd.Series, factor: float = C.SHORT_MIN_PRIOR_MARKUP) -> bool:
    """A Stage-2 markup happened within the last ~2 years: somewhere in that
    window the price rose >= factor from a preceding low to a later high.
    Filters perpetual Stage-4 losers out of the short scan."""
    lb = min(len(close), C.SHORT_MARKUP_LOOKBACK)
    if lb < 60:
        return False
    w = close.iloc[-lb:].values
    i_max = int(np.argmax(w))
    if i_max < 4:                       # high sits at the very start: no markup
        return False
    low_before = w[:i_max].min()
    return bool(low_before > 0 and w[i_max] / low_before >= factor)


def bearish_divergence(close: pd.Series, mrs: pd.Series) -> bool:
    """Price printed a 52w high within the last 26 weeks while current MRS < 0:
    relative strength broke before price."""
    if len(close) < 52 or mrs.dropna().empty:
        return False
    high_52w = close.iloc[-52:].max()
    recent_high = close.iloc[-26:].max()
    return bool(recent_high >= high_52w * 0.999 and mrs.iloc[-1] < 0)
