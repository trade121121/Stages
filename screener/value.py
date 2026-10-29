"""Greenblatt value screen ("Magic Formula") with Weinstein timing context.

Two ratios, ranked separately, ranks added:
  * Earnings yield   = EBIT / Enterprise Value
  * Return on capital = EBIT / (net working capital + net fixed assets)

Cheap AND good businesses score best in both. The formula alone has no
timing — cheap stocks can stay cheap for years (value trap). That is what
the stage columns are for: a value name in Stage 1 with MRS turning up is
the combination worth a chart look; one in Stage 4 is a falling knife.

Data: yfinance fundamentals, cached in docs/fundamentals.json (committed by
the workflow). Fundamentals change quarterly, so each run refreshes only the
stalest entries within a time budget; a full universe is covered after a few
weekly runs. Enterprise value is rebuilt every run from the current price
(shares x price + net debt), so the yield moves with the market even when
the balance sheet is cached.

Excluded per Greenblatt: financials and utilities (EBIT/EV meaningless for
banks/insurers; utilities are regulated returns). Real estate also excluded
(REIT EBIT is dominated by depreciation conventions).
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C

log = logging.getLogger("screener.value")

EXCLUDED_SECTORS = {"Financial Services", "Utilities", "Real Estate"}

_EBIT_ROWS = ("EBIT", "Operating Income")
_CASH_ROWS = ("Cash Cash Equivalents And Short Term Investments",
              "Cash And Cash Equivalents")
_CURDEBT_ROWS = ("Current Debt And Capital Lease Obligation", "Current Debt")
_PPE_ROWS = ("Net PPE",)
_DEBT_ROWS = ("Total Debt",)


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def _pick(df: pd.DataFrame | None, rows, col=0) -> float | None:
    if df is None or df.empty:
        return None
    for r in rows:
        if r in df.index:
            v = df.loc[r].iloc[col] if df.shape[1] > col else None
            if v is not None and pd.notna(v):
                return float(v)
    return None


def _ttm_ebit(t) -> tuple[float | None, str]:
    """Sum of last 4 quarters if complete, else latest annual."""
    try:
        q = t.quarterly_income_stmt
    except Exception:  # noqa: BLE001
        q = None
    if q is not None and not q.empty:
        for r in _EBIT_ROWS:
            if r in q.index:
                s = q.loc[r].iloc[:4]
                if len(s) == 4 and s.notna().all():
                    return float(s.sum()), "TTM"
    try:
        a = t.income_stmt
    except Exception:  # noqa: BLE001
        a = None
    v = _pick(a, _EBIT_ROWS)
    return v, "FY"


def fetch_one(ticker: str) -> dict | None:
    import yfinance as yf
    t = yf.Ticker(ticker)
    info = t.info or {}
    rec = {
        "ticker": ticker,
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "fin_currency": info.get("financialCurrency") or info.get("currency"),
        "shares": info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
    }
    if rec["sector"] in EXCLUDED_SECTORS:
        rec["excluded"] = True
        return rec
    ebit, basis = _ttm_ebit(t)
    try:
        bs = t.quarterly_balance_sheet
        if bs is None or bs.empty:
            raise ValueError
    except Exception:  # noqa: BLE001
        bs = t.balance_sheet
    ca = _pick(bs, ("Current Assets",))
    cl = _pick(bs, ("Current Liabilities",))
    cash = _pick(bs, _CASH_ROWS) or 0.0
    cur_debt = _pick(bs, _CURDEBT_ROWS) or 0.0
    rec.update({
        "ebit": ebit, "ebit_basis": basis,
        # Greenblatt: NWC = (current assets - cash) - (current liab. - short debt)
        "nwc": (ca - cash) - (cl - cur_debt) if ca is not None and cl is not None else None,
        "nfa": _pick(bs, _PPE_ROWS),
        "debt": _pick(bs, _DEBT_ROWS) or 0.0,
        "cash": cash,
    })
    return rec


def refresh_cache(tickers: list[str], path: str) -> dict:
    cache: dict = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except Exception:  # noqa: BLE001
            cache = {}
    today = datetime.now(timezone.utc).date()

    def age(tk):
        r = cache.get(tk)
        if not r or "fetched" not in r:
            return 10_000
        return (today - datetime.strptime(r["fetched"], "%Y-%m-%d").date()).days

    todo = [t for t in tickers if age(t) >= C.VALUE_TTL_DAYS]
    todo.sort(key=age, reverse=True)
    todo = todo[:C.VALUE_REFRESH_MAX]
    log.info("fundamentals: %d im Cache, %d zu aktualisieren", len(cache), len(todo))

    t0, errors, done = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=C.VALUE_WORKERS) as ex:
        futs = {ex.submit(fetch_one, t): t for t in todo}
        for f in as_completed(futs):
            tk = futs[f]
            try:
                rec = f.result()
                if rec:
                    cache[tk] = rec
                    done += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                if "Rate" in type(exc).__name__ or "Too Many" in str(exc):
                    log.warning("Rate-Limit — breche Fundamentals-Abruf ab")
                    for g in futs:
                        g.cancel()
                    break
            if time.time() - t0 > C.VALUE_TIME_BUDGET:
                log.warning("Zeitbudget erreicht — Rest nächste Woche")
                for g in futs:
                    g.cancel()
                break
    log.info("fundamentals: %d aktualisiert, %d Fehler, %.0fs", done, errors, time.time() - t0)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, separators=(",", ":"))
    return cache


# --------------------------------------------------------------------------
# currency
# --------------------------------------------------------------------------
def _quote_scale(cur: str | None) -> tuple[str | None, float]:
    """Minor units (GBp, ZAc, ILA) -> major currency + factor."""
    if cur in ("GBp", "GBX"):
        return "GBP", 0.01
    if cur == "ZAc":
        return "ZAR", 0.01
    if cur == "ILA":
        return "ILS", 0.01
    return cur, 1.0


def fx_pairs_needed(cache: dict) -> set[str]:
    pairs = set()
    for r in cache.values():
        q, _ = _quote_scale(r.get("currency"))
        f = r.get("fin_currency")
        if q and f and q != f:
            pairs.add(f"{q}{f}=X")
    return pairs


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------
def compute(cache: dict, weekly: dict, fx: dict[str, float]) -> list[dict]:
    """Return all eligible rows ranked by combined Greenblatt rank."""
    rows = []
    for tk, r in cache.items():
        if r.get("excluded") or tk not in weekly:
            continue
        ebit, nwc, nfa, shares = r.get("ebit"), r.get("nwc"), r.get("nfa"), r.get("shares")
        if not ebit or ebit <= 0 or not shares or nfa is None or nwc is None:
            continue
        price = float(weekly[tk]["close"].iloc[-1])
        qcur, scale = _quote_scale(r.get("currency"))
        fcur = r.get("fin_currency") or qcur
        rate = 1.0
        if qcur and fcur and qcur != fcur:
            rate = fx.get(f"{qcur}{fcur}=X")
            if not rate or not np.isfinite(rate):
                continue                        # unknown FX: skip, don't guess
        mcap = price * scale * shares * rate    # in financial currency
        ev = mcap + (r.get("debt") or 0.0) - (r.get("cash") or 0.0)
        cap = max(nwc, 0.0) + nfa               # Greenblatt floors NWC at 0
        if ev <= 0 or cap <= 0:
            continue
        rows.append({"ticker": tk, "sector": r.get("sector") or "?",
                     "industry": r.get("industry") or "",
                     "ey": ebit / ev * 100, "roc": ebit / cap * 100,
                     "ebit_basis": r.get("ebit_basis"), "fetched": r.get("fetched")})
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["rank_ey"] = df["ey"].rank(ascending=False, method="min")
    df["rank_roc"] = df["roc"].rank(ascending=False, method="min")
    df["rank"] = df["rank_ey"] + df["rank_roc"]
    df = df.sort_values(["rank", "rank_ey"]).reset_index(drop=True)
    df["pos"] = np.arange(1, len(df) + 1)
    return df.to_dict(orient="records")
