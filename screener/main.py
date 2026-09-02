"""Entry point: fetch universes -> download weekly data -> scan -> dashboard."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import yaml

from . import config as C
from . import constituents, data, intermarket, market, scanner
from .indicators import mansfield_rs, volume_ratio

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
                + list(bench_syms) + list(theme_syms)
                + list(C.WORLD_INDICES) + [C.PD_PROXY] + list(C.INTERMARKET))
    all_syms = list(dict.fromkeys(all_syms))

    # ------------------------------------------------ data ---------------
    weekly, failed = data.download_weekly(all_syms)
    log.info("downloaded %d ok / %d failed", len(weekly), len(failed))

    benches = {s: weekly[s]["close"] for s in bench_syms | theme_syms
               if s in weekly}
    for s in C.WORLD_INDICES:
        if s in weekly:
            benches.setdefault(s, weekly[s]["close"])
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
    # ------------------------------------------------ large-cap set -----
    # top-N by median weekly dollar volume, separately for US and Europe
    def _dv(t):
        wk = weekly[t]
        return float((wk["close"] * wk["volume"]).iloc[-52:].median())
    us_t = [t for t, u in zip(uni["ticker"], uni["universe"])
            if u in ("SPX", "NDX") and t in weekly]
    eu_t = [t for t, u in zip(uni["ticker"], uni["universe"])
            if u == "SXXP" and t in weekly]
    large = set(sorted(us_t, key=_dv, reverse=True)[:C.LARGE_TOP_US]
                + sorted(eu_t, key=_dv, reverse=True)[:C.LARGE_TOP_EU])
    names = dict(zip(uni["ticker"], uni["name"]))
    log.info("large-cap set: %d Ticker", len(large))

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
            if sig.side == "short" and C.SHORT_LARGE_ONLY and t not in large:
                continue                        # illiquid to short: skip
            (longs if sig.side == "long" else shorts).append(sig)

    # ------------------------------------------------ volume surge -------
    vol_rows = []
    for t in large:
        wk = weekly[t]
        if len(wk) < 60:
            continue
        vr = volume_ratio(wk["volume"])
        if not np.isfinite(vr):
            continue
        close = wk["close"]
        u = "SXXP" if t in eu_t else "SPX"
        bench = benches.get(local_bench_symbol(t, u))
        if bench is None:
            continue
        sma = close.rolling(C.MA_WEEKS).mean()
        m52 = mansfield_rs(close, bench)
        m13 = mansfield_rs(close, bench, weeks=C.MRS_SHORT_WEEKS)
        chg = float(close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) > 1 else 0.0
        vol_rows.append({
            "ticker": t, "name": str(names.get(t, t)), "universe": u,
            "vol_ratio": round(float(vr), 2),
            "chg_w": round(chg, 1),
            "close": round(float(close.iloc[-1]), 2),
            "vs_ma": round(float(close.iloc[-1] / sma.iloc[-1] - 1) * 100, 1)
            if np.isfinite(sma.iloc[-1]) else None,
            "mrs": round(float(m52.iloc[-1]), 1) if np.isfinite(m52.iloc[-1]) else None,
            "mrs13": round(float(m13.iloc[-1]), 1) if np.isfinite(m13.iloc[-1]) else None,
            "mrs_chg_4w": round(float(m52.iloc[-1] - m52.iloc[-5]), 1)
            if len(m52.dropna()) >= 5 else None,
            "spark_close": [round(float(v), 4) for v in close.iloc[-52:]],
            "spark_sma": [round(float(v), 4) if np.isfinite(v) else None
                          for v in sma.iloc[-52:]],
            "spark_mrs": [round(float(v), 3) if np.isfinite(v) else None
                          for v in m52.iloc[-52:]],
            "side": "long" if chg >= 0 else "short",
        })
    vol_rows.sort(key=lambda r: -r["vol_ratio"])
    vol_rows = vol_rows[:C.VOLUME_TAB_N]

    # ------------------------------------------------ RS accelerators ----
    # who is starting to outperform: biggest MRS improvement over N weeks,
    # coming from weakness (the early footprint, before Stage 2 is obvious)
    acc_rows = []
    for t in large:
        wk = weekly[t]
        u = "SXXP" if t in eu_t else "SPX"
        bench = benches.get(local_bench_symbol(t, u))
        if bench is None or len(wk) < 80:
            continue
        close = wk["close"]
        m52 = mansfield_rs(close, bench).dropna()
        if len(m52) <= C.RS_ACCEL_WEEKS + 1:
            continue
        now, then = float(m52.iloc[-1]), float(m52.iloc[-1 - C.RS_ACCEL_WEEKS])
        if then > 0 or now <= then:
            continue                            # must come from weakness, improving
        m13 = mansfield_rs(close, bench, weeks=C.MRS_SHORT_WEEKS)
        sma = close.rolling(C.MA_WEEKS).mean()
        acc_rows.append({
            "ticker": t, "name": str(names.get(t, t)), "universe": u,
            "mrs": round(now, 1), "mrs_then": round(then, 1),
            "delta": round(now - then, 1),
            "mrs13": round(float(m13.iloc[-1]), 1) if np.isfinite(m13.iloc[-1]) else None,
            "lead": bool(np.isfinite(m13.iloc[-1]) and m13.iloc[-1] > 0 and now <= 0),
            "close": round(float(close.iloc[-1]), 2),
            "vs_ma": round(float(close.iloc[-1] / sma.iloc[-1] - 1) * 100, 1)
            if np.isfinite(sma.iloc[-1]) else None,
            "spark_close": [round(float(v), 4) for v in close.iloc[-52:]],
            "spark_sma": [round(float(v), 4) if np.isfinite(v) else None
                          for v in sma.iloc[-52:]],
            "spark_mrs": [round(float(v), 3) if np.isfinite(v) else None
                          for v in mansfield_rs(close, bench).iloc[-52:]],
            "side": "long",
        })
    acc_rows.sort(key=lambda r: -r["delta"])
    acc_rows = acc_rows[:C.RS_ACCEL_N]
    log.info("volume rows %d · RS accelerators %d", len(vol_rows), len(acc_rows))

    # ---- mark what is NEW versus previous runs -------------------------
    hist_path = os.path.join(root, C.OUTPUT_DIR, "signals_history.json")
    runs = []
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as fh:
                runs = json.load(fh)
        except Exception:  # noqa: BLE001
            runs = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    runs = [r for r in runs if r.get("date") != today]

    prev = runs[-1]["signals"] if runs else {}
    for sig in longs + shorts:
        sig.is_new = prev.get(sig.ticker) != sig.signal_type
        n = 1
        for run in reversed(runs):
            if run.get("signals", {}).get(sig.ticker) == sig.signal_type:
                n += 1
            else:
                break
        sig.weeks_on_list = n

    runs.append({"date": today,
                 "signals": {s.ticker: s.signal_type for s in longs + shorts}})
    runs = runs[-C.SIGNAL_HISTORY_RUNS:]
    with open(hist_path, "w", encoding="utf-8") as fh:
        json.dump(runs, fh)
    log.info("neu diese Woche: %d von %d Signalen",
             sum(1 for s in longs + shorts if s.is_new), len(longs) + len(shorts))

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

    # ------------------------------------------------ macro gauges -------
    try:
        macro = market.compute(weekly, uni, benches)
        log.info("macro score %.1f (%s)", macro["score"], macro["label"])
        macro["history"] = market.log_history(
            macro, os.path.join(root, C.OUTPUT_DIR, "macro_history.csv"))
    except Exception as exc:  # noqa: BLE001
        log.warning("macro module failed: %r", exc)
        macro = None
        issues.append(f"Marktlage-Modul fehlgeschlagen: {exc!r}")

    # ------------------------------------------------ intermarket --------
    try:
        inter = intermarket.compute(weekly)
        log.info("intermarket: %d Warnungen, %d Beobachtungen",
                 inter["n_warn"], inter["n_watch"])
    except Exception as exc:  # noqa: BLE001
        log.warning("intermarket failed: %r", exc)
        inter = None
        issues.append(f"Intermarket-Modul fehlgeschlagen: {exc!r}")

    # ------------------------------------------------ render -------------
    from . import dashboard
    bench_wk = weekly.get(C.BENCH_US)
    week_end = (bench_wk.index[-1].strftime("%d.%m.%Y")
                if bench_wk is not None and len(bench_wk) else "?")
    stats = {"tickers": len(uni), "failed": len(failed), "week_end": week_end}
    log.info("ausgewertete Woche endet am %s", week_end)
    issues += [f"no data: {t}" for t in failed[:60]]
    html = dashboard.render(longs, shorts, sectors, wl_rows, issues, stats,
                            macro, vol_rows=vol_rows, acc_rows=acc_rows,
                            inter=inter)
    out = os.path.join(root, C.OUTPUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("dashboard written: %s", out)


if __name__ == "__main__":
    run()
