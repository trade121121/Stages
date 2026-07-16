"""Entry point: fetch universes -> download weekly data -> scan -> dashboard."""
from __future__ import annotations

import logging
import os

import numpy as np
import yaml

from . import config as C
from . import constituents, data, scanner
from .indicators import mansfield_rs

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("main")

# Which local benchmark applies to which universe / ticker suffix
def local_bench_symbol(ticker: str, universe: str) -> str:
    if universe == "SXXP":
        return C.BENCH_EU
    if ticker.endswith(".HK"):
        return C.BENCH_HK
    return C.BENCH_US


def run() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(root, C.OUTPUT_DIR), exist_ok=True)

    # ------------------------------------------------ universes ----------
    uni, issues = constituents.load_all()
    log.info("universe: %d tickers", len(uni))

    with open(os.path.join(root, "watchlists.yaml"), encoding="utf-8") as fh:
        wl_cfg = yaml.safe_load(fh) or {}

    wl_tickers = []
    for wl in wl_cfg.get("watchlists", []):
        wl_tickers += wl.get("tickers", [])

    bench_syms = {C.BENCH_US, C.BENCH_EU, C.BENCH_HK}
    theme_syms = {wl.get("theme_benchmark") for wl in wl_cfg.get("watchlists", [])
                  if wl.get("theme_benchmark")}
    all_syms = (list(uni["ticker"]) + wl_tickers + list(C.SECTOR_ETFS)
                + list(bench_syms) + list(theme_syms))
    all_syms = list(dict.fromkeys(all_syms))

    # ------------------------------------------------ data ---------------
    weekly, failed = data.download_weekly(all_syms)
    log.info("downloaded %d ok / %d failed", len(weekly), len(failed))

    benches = {s: weekly[s]["close"] for s in bench_syms | theme_syms
               if s in weekly}
    if C.BENCH_US not in benches:
        raise SystemExit("S&P 500 benchmark data missing — aborting")

    # ------------------------------------------------ sector rotation ----
    sector_weekly = {s: weekly.get(s) for s in C.SECTOR_ETFS}
    sectors = scanner.sector_table(sector_weekly, benches[C.BENCH_US])
    sector_mrs_map = dict(zip(sectors["symbol"], sectors["mrs"])) \
        if len(sectors) else {}

    # crude ticker->sector context via universe tag (SPX/NDX -> XLK etc. is
    # not knowable without GICS mapping; we attach the *theme* ETF where a
    # watchlist defines one, otherwise leave None)
    # ------------------------------------------------ main scan ----------
    longs, shorts = [], []
    for _, row in uni.iterrows():
        t = row["ticker"]
        if t not in weekly:
            continue
        bench = benches.get(local_bench_symbol(t, row["universe"]))
        if bench is None:
            continue
        sig = scanner.evaluate(t, str(row["name"]), row["universe"],
                               weekly[t], bench)
        if sig:
            (longs if sig.side == "long" else shorts).append(sig)

    longs.sort(key=lambda s: -s.score)
    shorts.sort(key=lambda s: -s.score)
    log.info("signals: %d long / %d short", len(longs), len(shorts))

    # ------------------------------------------------ watchlists ---------
    wl_rows = []
    for wl in wl_cfg.get("watchlists", []):
        lb = benches.get(wl.get("local_benchmark", C.BENCH_US))
        tb = benches.get(wl.get("theme_benchmark"))
        for t in wl.get("tickers", []):
            wk = weekly.get(t)
            if wk is None or lb is None or len(wk) < C.MRS_WEEKS + 2:
                issues.append(f"watchlist {wl['name']}: no data for {t}")
                continue
            close = wk["close"]
            sma = close.rolling(C.MA_WEEKS).mean()
            row = {"ticker": t, "list": wl["name"],
                   "close": round(float(close.iloc[-1]), 2),
                   "vs_ma": round(float(close.iloc[-1] / sma.iloc[-1] - 1), 4)
                   if np.isfinite(sma.iloc[-1]) else None,
                   "mrs_local": round(float(
                       mansfield_rs(close, lb).iloc[-1]), 2),
                   "mrs_theme": None, "quadrant": None, "signal": None}
            if tb is not None:
                dm = scanner.dual_mrs_matrix(wk, lb, tb)
                row.update(mrs_theme=dm["mrs_theme"], quadrant=dm["quadrant"],
                           mrs_local=dm["mrs_local"])
            sig = scanner.evaluate(t, t, wl["name"], wk, lb)
            if sig:
                row["signal"] = f"{sig.side.upper()} (Score {sig.score})"
            wl_rows.append(row)

    # ------------------------------------------------ sector context -----
    theme_of_universe = {"SPX": None, "NDX": None, "SXXP": None}
    for s in longs + shorts:
        s.sector_mrs = theme_of_universe.get(s.universe)

    # ------------------------------------------------ render -------------
    from . import dashboard
    stats = {"tickers": len(uni), "failed": len(failed)}
    issues += [f"no data: {t}" for t in failed[:60]]
    html = dashboard.render(longs, shorts, sectors, wl_rows, issues, stats)
    out = os.path.join(root, C.OUTPUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("dashboard written: %s", out)


if __name__ == "__main__":
    run()
