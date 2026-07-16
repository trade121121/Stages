"""Universe constituents, fetched at runtime (GitHub Actions has open network).

SPX / NDX: Wikipedia tables (stable for years).
STOXX 600: iShares EXSA holdings CSV, exchange -> yfinance suffix mapping.
           Unresolved rows are reported, never silently dropped.
Fallback:  data/stoxx600_fallback.csv (ticker,name) if the download fails.
"""
from __future__ import annotations

import io
import logging
import os

import pandas as pd
import requests

from . import config as C

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (weinstein-screener)"}

WIKI_SPX = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_NDX = "https://en.wikipedia.org/wiki/Nasdaq-100"


def _wiki_tables(url: str) -> list[pd.DataFrame]:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def sp500() -> pd.DataFrame:
    for t in _wiki_tables(WIKI_SPX):
        if "Symbol" in t.columns and "Security" in t.columns:
            df = t[["Symbol", "Security"]].copy()
            df.columns = ["ticker", "name"]
            df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
            df["universe"] = "SPX"
            return df
    raise RuntimeError("SPX table not found on Wikipedia")


def nasdaq100() -> pd.DataFrame:
    for t in _wiki_tables(WIKI_NDX):
        cols = {c.lower(): c for c in map(str, t.columns)}
        tick = cols.get("ticker") or cols.get("symbol")
        name = cols.get("company")
        if tick and name and len(t) > 80:
            df = t[[tick, name]].copy()
            df.columns = ["ticker", "name"]
            df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
            df["universe"] = "NDX"
            return df
    raise RuntimeError("NDX table not found on Wikipedia")


def stoxx600() -> tuple[pd.DataFrame, list[str]]:
    """Returns (constituents, unresolved_report)."""
    unresolved: list[str] = []
    try:
        r = requests.get(C.ISHARES_STOXX600_CSV, headers=HEADERS, timeout=60)
        r.raise_for_status()
        raw = r.content.decode("utf-8-sig", errors="replace")
        # iShares CSVs carry preamble lines before the header row
        lines = raw.splitlines()
        start = next(i for i, ln in enumerate(lines)
                     if ln.lower().startswith(("ticker", "\"ticker")))
        df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
        df = df.rename(columns={c: c.strip() for c in df.columns})
        tick_col = next(c for c in df.columns if c.lower().startswith("ticker"))
        name_col = next((c for c in df.columns if "name" in c.lower()), tick_col)
        exch_col = next((c for c in df.columns
                         if "exchange" in c.lower() or "börse" in c.lower()), None)

        rows = []
        for _, row in df.iterrows():
            local = str(row[tick_col]).strip()
            if not local or local in ("-", "nan"):
                continue
            exch = str(row[exch_col]).strip() if exch_col else ""
            suffix = C.EXCHANGE_SUFFIX.get(exch)
            if suffix is None:
                unresolved.append(f"{local} ({exch})")
                continue
            rows.append({"ticker": local.replace(" ", "-") + suffix,
                         "name": str(row[name_col]).strip(),
                         "universe": "SXXP"})
        out = pd.DataFrame(rows).drop_duplicates("ticker")
        if len(out) < 300:
            raise RuntimeError(f"only {len(out)} STOXX tickers resolved")
        return out, unresolved
    except Exception as exc:  # noqa: BLE001
        log.warning("STOXX600 download failed (%s), using fallback CSV", exc)
        fb = os.path.join(os.path.dirname(__file__), "..",
                          "data", "stoxx600_fallback.csv")
        df = pd.read_csv(fb)
        df["universe"] = "SXXP"
        return df, [f"LIVE FETCH FAILED: {exc} — fallback list in use"]


def load_all() -> tuple[pd.DataFrame, list[str]]:
    frames, report = [], []
    for fn in (sp500, nasdaq100):
        try:
            frames.append(fn())
        except Exception as exc:  # noqa: BLE001
            report.append(f"{fn.__name__} failed: {exc}")
    stx, unres = stoxx600()
    frames.append(stx)
    report.extend(unres)
    uni = pd.concat(frames, ignore_index=True)
    # NDX overlaps SPX almost fully -> keep first occurrence, tag stays
    uni = uni.drop_duplicates("ticker", keep="first").reset_index(drop=True)
    return uni, report
