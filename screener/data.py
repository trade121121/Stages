"""Batched yfinance downloads with retries -> weekly OHLCV per ticker."""
from __future__ import annotations

import logging
import time

import pandas as pd
import yfinance as yf

from . import config as C
from .indicators import to_weekly

log = logging.getLogger(__name__)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.dropna(subset=["close"])


def download_weekly(tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Returns ({ticker: weekly_df}, failed_tickers)."""
    weekly: dict[str, pd.DataFrame] = {}
    failed: list[str] = []

    for i in range(0, len(tickers), C.BATCH_SIZE):
        batch = tickers[i:i + C.BATCH_SIZE]
        for attempt in range(1, C.MAX_RETRIES + 1):
            try:
                raw = yf.download(
                    batch, period=C.HISTORY_PERIOD, interval="1d",
                    auto_adjust=True, group_by="ticker",
                    threads=True, progress=False,
                )
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("batch %d attempt %d failed: %s", i, attempt, exc)
                time.sleep(5 * attempt)
        else:
            failed.extend(batch)
            continue

        for t in batch:
            try:
                df = raw[t] if len(batch) > 1 else raw
                df = _normalise(df.dropna(how="all"))
                if len(df) < 200:          # ~10 months of daily bars minimum
                    failed.append(t)
                    continue
                weekly[t] = to_weekly(df)
            except Exception:  # noqa: BLE001
                failed.append(t)
        time.sleep(1.0)                    # be polite between batches

    return weekly, failed
