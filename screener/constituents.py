"""Universe constituents, fetched at runtime (GitHub Actions has open network).

SPX / NDX: Wikipedia tables (robust column detection, logs columns on failure).
STOXX 600: iShares EXSA holdings CSV — handles German AND English headers
           (Emittententicker/Ticker, Boerse/Exchange), case-insensitive
           exchange -> yfinance suffix mapping. Unresolved rows are reported.
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

# extra exchange spellings seen in iShares files (merged case-insensitively
# with config.EXCHANGE_SUFFIX)
_EXTRA_SUFFIX = {
    "nasdaq stockholm": ".ST", "nasdaq helsinki": ".HE",
    "nasdaq copenhagen": ".CO", "nasdaq omx nordic": ".ST",
    "deutsche boerse xetra": ".DE", "xetra (frankfurt)": ".DE",
    "bolsa de madrid": ".MC", "euronext dublin": ".IR",
    "borsa italiana s.p.a.": ".MI", "euronext milan": ".MI",
    "six swiss exchange ag": ".SW", "oslo bors asa": ".OL",
    "wiener boerse": ".VI", "london stock exchange plc": ".L",
}


def _suffix_map() -> dict[str, str]:
    m = {k.strip().lower(): v for k, v in C.EXCHANGE_SUFFIX.items()}
    m.update(_EXTRA_SUFFIX)
    return m


# substring -> suffix, checked in order (first hit wins); robust against
# verbose iShares exchange names like "Nyse Euronext - Euronext Paris"
_SUFFIX_PATTERNS = [
    ("paris", ".PA"), ("brussels", ".BR"), ("amsterdam", ".AS"),
    ("lisbon", ".LS"), ("milan", ".MI"), ("italiana", ".MI"),
    ("xetra", ".DE"), ("frankfurt", ".DE"), ("deutsche", ".DE"),
    ("copenhagen", ".CO"), ("stockholm", ".ST"), ("helsinki", ".HE"),
    ("oslo", ".OL"), ("swiss", ".SW"), ("zurich", ".SW"),
    ("madrid", ".MC"), ("london", ".L"), ("dublin", ".IR"),
    ("irish", ".IR"), ("wiener", ".VI"), ("vienna", ".VI"),
    ("warsaw", ".WA"), ("athens", ".AT"), ("prague", ".PR"),
    ("budapest", ".BD"), ("berlin", ".BE"),
]


def _suffix_for(exch: str, smap: dict[str, str]) -> str | None:
    e = exch.strip().lower()
    if e in smap:
        return smap[e]
    for pat, suf in _SUFFIX_PATTERNS:
        if pat in e:
            return suf
    return None


def _flat_cols(df: pd.DataFrame) -> list[str]:
    """Flatten (Multi)Index columns to lowercase strings."""
    out = []
    for c in df.columns:
        if isinstance(c, tuple):
            c = " ".join(str(x) for x in c if str(x) != "nan")
        out.append(str(c).strip().lower())
    return out


def _wiki_tables(url: str) -> list[pd.DataFrame]:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def _extract(t: pd.DataFrame, tick_keys, name_keys,
             min_rows: int) -> pd.DataFrame | None:
    cols = _flat_cols(t)
    t = t.copy()
    t.columns = cols
    tick = next((c for c in cols if any(k in c for k in tick_keys)), None)
    name = next((c for c in cols if any(k in c for k in name_keys)), None)
    if not tick or not name or len(t) < min_rows:
        return None
    df = t[[tick, name]].copy()
    df.columns = ["ticker", "name"]
    df["ticker"] = (df["ticker"].astype(str).str.strip()
                    .str.replace(".", "-", regex=False))
    df = df[df["ticker"].str.len().between(1, 6)]
    return df if len(df) >= min_rows else None


def sp500() -> pd.DataFrame:
    tables = _wiki_tables(WIKI_SPX)
    for t in tables:
        df = _extract(t, ("symbol", "ticker"), ("security", "company"), 400)
        if df is not None:
            df["universe"] = "SPX"
            return df
    log.error("SPX columns seen: %s", [_flat_cols(t) for t in tables[:4]])
    raise RuntimeError("SPX table not found on Wikipedia")


QQQ_HOLDINGS_CSV = (
    "https://www.invesco.com/us/financial-products/etfs/holdings/main/"
    "holdings/0?audienceType=Investor&action=download&ticker=QQQ"
)


def _ndx_from_qqq() -> pd.DataFrame:
    """Nasdaq-100 via Invesco QQQ holdings CSV (source of truth: the ETF)."""
    r = requests.get(QQQ_HOLDINGS_CSV, headers=HEADERS, timeout=60)
    r.raise_for_status()
    raw = r.content.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}
    tick_col = next((low[c] for c in low if "holding ticker" in c), None) \
        or next((low[c] for c in low if "ticker" in c and "fund" not in c), None)
    name_col = next((low[c] for c in low if c == "name" or "name" in c), tick_col)
    if tick_col is None:
        raise RuntimeError(f"QQQ CSV: no ticker column in {list(df.columns)!r}")
    out = df[[tick_col, name_col]].copy()
    out.columns = ["ticker", "name"]
    out["ticker"] = (out["ticker"].astype(str).str.strip()
                     .str.replace(".", "-", regex=False))
    out = out[out["ticker"].str.len().between(1, 6)]
    if len(out) < 90 or "AAPL" not in set(out["ticker"]):
        raise RuntimeError(f"QQQ CSV implausible ({len(out)} rows)")
    out["universe"] = "NDX"
    return out.drop_duplicates("ticker")


def nasdaq100() -> pd.DataFrame:
    tables = _wiki_tables(WIKI_NDX)
    for t in tables:
        df = _extract(t, ("ticker", "symbol"), ("company", "security"), 90)
        if df is not None:
            df["universe"] = "NDX"
            return df
    # fallback: find the table whose VALUES contain known anchor tickers,
    # independent of whatever Wikipedia currently calls the columns
    anchors = {"AAPL", "MSFT", "NVDA"}
    for t in tables:
        t = t.copy()
        t.columns = _flat_cols(t)
        for col in t.columns:
            vals = set(t[col].astype(str).str.strip())
            if anchors <= vals and len(t) >= 90:
                others = [c for c in t.columns if c != col]
                name_col = next(
                    (c for c in others
                     if t[c].astype(str).str.len().mean() > 6), others[0])
                df = t[[col, name_col]].copy()
                df.columns = ["ticker", "name"]
                df["ticker"] = (df["ticker"].astype(str).str.strip()
                                .str.replace(".", "-", regex=False))
                df = df[df["ticker"].str.len().between(1, 6)]
                df["universe"] = "NDX"
                log.info("NDX resolved via anchor fallback (col=%r)", col)
                return df
    log.warning("NDX not found on Wikipedia, trying QQQ holdings CSV")
    return _ndx_from_qqq()


def stoxx600() -> tuple[pd.DataFrame, list[str]]:
    """Returns (constituents, unresolved_report)."""
    unresolved: list[str] = []
    try:
        r = requests.get(C.ISHARES_STOXX600_CSV, headers=HEADERS, timeout=60)
        r.raise_for_status()
        raw = r.content.decode("utf-8-sig", errors="replace")
        lines = raw.splitlines()
        # header row = first line whose first cell CONTAINS "ticker"
        # (German file: "Emittententicker"; English file: "Ticker")
        start = None
        for i, ln in enumerate(lines):
            first_cell = ln.split(",")[0].split(";")[0].strip().strip('"').lower()
            if "ticker" in first_cell:
                start = i
                break
        if start is None:
            raise RuntimeError(
                f"no ticker header found; first lines: {lines[:3]!r}")
        body = "\n".join(lines[start:])
        sep = ";" if lines[start].count(";") > lines[start].count(",") else ","
        df = pd.read_csv(io.StringIO(body), sep=sep)
        df.columns = [str(c).strip() for c in df.columns]

        low = {c.lower(): c for c in df.columns}
        tick_col = next((low[c] for c in low if "ticker" in c), None)
        name_col = next((low[c] for c in low if "name" in c), tick_col)
        exch_col = next((low[c] for c in low
                         if "exchange" in c or "börse" in c or "boerse" in c),
                        None)
        if tick_col is None:
            raise RuntimeError(f"no ticker column in {list(df.columns)!r}")

        smap = _suffix_map()
        rows = []
        for _, row in df.iterrows():
            local = str(row[tick_col]).strip()
            if not local or local.lower() in ("-", "nan", ""):
                continue
            exch = (str(row[exch_col]).strip() if exch_col else "")
            if exch in ("-", "", "nan") or local in ("EUR", "USD", "GBP", "CHF"):
                continue                      # ETF cash / FX lines
            suffix = _suffix_for(exch, smap)
            if suffix is None:
                unresolved.append(f"{local} ({exch})")
                continue
            clean = local.rstrip(".").replace(".", "-").replace(" ", "-")
            rows.append({"ticker": clean + suffix,
                         "name": str(row[name_col]).strip(),
                         "universe": "SXXP"})
        out = pd.DataFrame(rows).drop_duplicates("ticker")
        if len(out) < 300:
            raise RuntimeError(
                f"only {len(out)} STOXX tickers resolved; "
                f"unresolved sample: {unresolved[:8]!r}")
        return out, unresolved
    except Exception as exc:  # noqa: BLE001
        log.warning("STOXX600 download failed (%r), using fallback CSV", exc)
        fb = os.path.join(os.path.dirname(__file__), "..",
                          "data", "stoxx600_fallback.csv")
        df = pd.read_csv(fb)
        df["universe"] = "SXXP"
        return df, [f"LIVE FETCH FAILED: {exc!r} — fallback list in use"]


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
    uni = uni.drop_duplicates("ticker", keep="first").reset_index(drop=True)
    return uni, report
