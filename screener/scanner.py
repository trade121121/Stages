"""Long (Stage 1->2) and Short (Stage 3->4) scanners on weekly bars."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I


@dataclass
class Signal:
    ticker: str
    name: str
    universe: str
    side: str                 # "long" | "short"
    close: float
    sma30: float
    slope6: float
    mrs: float
    mrs_fresh_cross: bool
    vol_ratio: float
    base_weeks: int
    base_vol: float
    divergence: bool
    vol_bonus: bool
    score: float
    spark_close: list = field(default_factory=list)
    spark_sma: list = field(default_factory=list)
    spark_mrs: list = field(default_factory=list)
    sector_mrs: float | None = None


def _sparks(close: pd.Series, sma: pd.Series, mrs: pd.Series, n: int = 52):
    def tail(s):
        vals = s.iloc[-n:].astype(float)
        return [None if not np.isfinite(v) else round(float(v), 4) for v in vals]
    return tail(close), tail(sma), tail(mrs)


def evaluate(ticker: str, name: str, universe: str,
             weekly: pd.DataFrame, bench_close: pd.Series) -> Signal | None:
    """Run both scanners on one ticker. Returns a Signal or None."""
    if len(weekly) < C.MIN_WEEKS_REQUIRED:
        return None

    close, vol = weekly["close"], weekly["volume"]
    sma = close.rolling(C.MA_WEEKS).mean()
    slope = I.sma_slope(sma)
    mrs = I.mansfield_rs(close, bench_close)

    if not np.isfinite(sma.iloc[-1]) or not np.isfinite(mrs.iloc[-1]):
        return None

    c, s, sl, m = float(close.iloc[-1]), float(sma.iloc[-1]), \
        float(slope.iloc[-1]), float(mrs.iloc[-1])
    vr = I.volume_ratio(vol)
    base_weeks = I.weeks_since_52w_low(close)
    base_vol = I.base_volatility(close)
    fresh = I.fresh_cross_up(mrs)

    prior_max_close = close.iloc[-(C.BREAKOUT_WINDOW + 1):-1].max()
    prior_min_close = close.iloc[-(C.BREAKOUT_WINDOW + 1):-1].min()
    is_26w_high = c >= prior_max_close
    is_26w_low = c <= prior_min_close

    # ----------------------------------------------------------- LONG -----
    long_ok = (
        c > s
        and sl > 0
        and m > 0
        and is_26w_high
        and c <= prior_max_close * (1 + C.LONG_MAX_EXT_OVER_BASE)
        and base_weeks >= C.LONG_MIN_BASE_WEEKS
        and I.ma_crossings(close, sma) >= C.LONG_MIN_MA_CROSSINGS
        and I.ma_was_flat(slope)
        and np.isfinite(vr) and vr >= C.LONG_MIN_VOL_RATIO
    )
    if long_ok:
        score = (
            min(vr, 4.0) * 2.0                      # breakout volume
            + (3.0 if fresh else 0.0)               # fresh MRS cross
            + min(m, 15.0) * 0.2                    # MRS level
            + (min(base_vol, 1.5) * 2.0 if np.isfinite(base_vol) else 0)  # wild base bonus
            + min(base_weeks, 52) / 13.0            # base maturity
        )
        sc, ss, sm = _sparks(close, sma, mrs)
        return Signal(ticker, name, universe, "long", c, s, sl, m, fresh,
                      vr if np.isfinite(vr) else float("nan"),
                      base_weeks, base_vol if np.isfinite(base_vol) else float("nan"),
                      False, False, round(score, 2), sc, ss, sm)

    # ---------------------------------------------------------- SHORT -----
    div = I.bearish_divergence(close, mrs)
    short_ok = (
        c < s
        and sl <= 0
        and m < 0
        and is_26w_low
        and I.prior_markup(close)
    )
    if short_ok:
        vol_bonus = np.isfinite(vr) and vr >= C.SHORT_VOL_BONUS_RATIO
        score = (
            min(abs(m), 15.0) * 0.3                 # RS weakness
            + (3.0 if div else 0.0)                 # RS broke before price
            + min(abs(sl) * 100, 5.0)               # MA rollover severity
            + (2.0 if vol_bonus else 0.0)           # volume = bonus, not filter
        )
        sc, ss, sm = _sparks(close, sma, mrs)
        return Signal(ticker, name, universe, "short", c, s, sl, m, fresh,
                      vr if np.isfinite(vr) else float("nan"),
                      base_weeks, base_vol if np.isfinite(base_vol) else float("nan"),
                      div, bool(vol_bonus), round(score, 2), sc, ss, sm)

    return None


def sector_table(sector_weekly: dict[str, pd.DataFrame],
                 bench_close: pd.Series) -> pd.DataFrame:
    """MRS + 4-week MRS change for every sector/theme ETF vs. S&P 500."""
    rows = []
    for sym, wk in sector_weekly.items():
        if wk is None or len(wk) < C.MRS_WEEKS + 6:
            continue
        mrs = I.mansfield_rs(wk["close"], bench_close).dropna()
        if len(mrs) < 5:
            continue
        rows.append({
            "symbol": sym,
            "name": C.SECTOR_ETFS.get(sym, sym),
            "mrs": round(float(mrs.iloc[-1]), 2),
            "mrs_chg_4w": round(float(mrs.iloc[-1] - mrs.iloc[-5]), 2),
            "spark_mrs": [round(float(v), 3) for v in mrs.iloc[-52:]],
        })
    df = pd.DataFrame(rows)
    return df.sort_values("mrs", ascending=False) if not df.empty else df


def dual_mrs_matrix(weekly: pd.DataFrame, local_bench: pd.Series,
                    theme_bench: pd.Series) -> dict:
    """China-robotics style dual MRS: vs. local index and vs. theme ETF."""
    m_local = I.mansfield_rs(weekly["close"], local_bench).iloc[-1]
    m_theme = I.mansfield_rs(weekly["close"], theme_bench).iloc[-1]
    quad = ("leader" if m_local > 0 and m_theme > 0 else
            "beta_only" if m_local > 0 else
            "discounted_strength" if m_theme > 0 else "avoid")
    return {"mrs_local": round(float(m_local), 2),
            "mrs_theme": round(float(m_theme), 2),
            "quadrant": quad}
