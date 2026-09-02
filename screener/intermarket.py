"""Intermarket regime monitor.

Not Weinstein — this is Murphy-style intermarket analysis, complementary to
the stage work. The point is to surface REGIME changes that single-stock
charts cannot see: the yield curve re-steepening out of an inversion, credit
spreads widening under a calm index, dollar and gold rising together, a yen
squeeze, or the index making highs that its own breadth proxies do not
confirm. Each rule is explicit and explainable; no composite score here,
because these signals are not commensurable — a curve inversion and a copper
slide are different kinds of information and should be read as such.

One deliberate omission: DXY vs. EUR/USD "divergence". The euro is ~57% of
the dollar index, so the two are near-mechanically inverse; what looks like a
divergence is just yen and sterling moving. Not a signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import indicators as I
from .market import classify_stage, STAGE_NAME


def _chg(s: pd.Series, weeks: int) -> float:
    s = s.dropna()
    if len(s) <= weeks:
        return float("nan")
    a, b = float(s.iloc[-1]), float(s.iloc[-1 - weeks])
    return (a / b - 1.0) * 100.0 if b else float("nan")


def _diff(s: pd.Series, weeks: int) -> float:
    """Absolute change (for yields, which are already in %)."""
    s = s.dropna()
    if len(s) <= weeks:
        return float("nan")
    return float(s.iloc[-1] - s.iloc[-1 - weeks])


def _weeks_since_high(s: pd.Series, window: int = 52) -> int:
    w = s.dropna().iloc[-window:]
    if len(w) < 3:
        return 999
    return int(len(w) - 1 - int(np.argmax(w.values)))


def _row(sym: str, wk: pd.DataFrame, is_yield: bool) -> dict:
    c = wk["close"]
    sma = c.rolling(C.MA_WEEKS).mean()
    sl = I.sma_slope(sma)
    st = classify_stage(float(c.iloc[-1]), float(sma.iloc[-1]),
                        float(sl.iloc[-1]))
    name, group = C.INTERMARKET[sym]
    if is_yield:
        c4, c13 = _diff(c, 4) * 100, _diff(c, 13) * 100     # in basis points
        unit = "Bp"
    else:
        c4, c13 = _chg(c, 4), _chg(c, 13)
        unit = "%"
    return {
        "symbol": sym, "name": name, "group": group,
        "level": round(float(c.iloc[-1]), 3 if is_yield else 2),
        "chg4": round(c4, 1) if np.isfinite(c4) else None,
        "chg13": round(c13, 1) if np.isfinite(c13) else None,
        "unit": unit,
        "high_age": _weeks_since_high(c),
        "stage": st, "stage_name": STAGE_NAME[st],
        "spark": [round(float(v), 4) for v in c.iloc[-52:]],
    }


def compute(weekly: dict[str, pd.DataFrame]) -> dict:
    yields = {"^TNX", "^TYX", "^IRX"}
    rows, ser = [], {}
    for sym in C.INTERMARKET:
        wk = weekly.get(sym)
        if wk is None or len(wk) < C.MA_WEEKS + 20:
            continue
        rows.append(_row(sym, wk, sym in yields))
        ser[sym] = wk["close"]

    signals: list[dict] = []

    def add(key, active, level, value, why):
        signals.append({"key": key, "active": bool(active), "level": level,
                        "value": value, "why": why})

    g = ser.get
    spx, ndx, rut, djt, dji = g("^GSPC"), g("^IXIC"), g("^RUT"), g("^DJT"), g("^DJI")

    # ---- 1) Leadership: does breadth confirm the index? ---------------------
    if spx is not None:
        spx_hi = _weeks_since_high(spx) <= 4
        near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.97)
        for proxy, nm, txt in ((rut, "Russell 2000", "schmale Führung — Small Caps bestätigen nicht"),
                               (djt, "Dow Transports", "Dow-Theorie: Transports bestätigen nicht"),
                               (ndx, "Nasdaq", "Tech bestätigt den S&P nicht mehr")):
            if proxy is None:
                continue
            p_hi = _weeks_since_high(proxy) <= 8
            active = spx_hi and not p_hi
            add(f"S&P-Hoch ohne {nm}", active, "warn" if active else "ok",
                f"S&P-Hoch vor {_weeks_since_high(spx)}W · {nm}-Hoch vor {_weeks_since_high(proxy)}W",
                txt if active else f"{nm} bestätigt")
        if ndx is not None:
            n_hi, s_hi = _weeks_since_high(ndx) <= 4, _weeks_since_high(spx) <= 8
            active = n_hi and not s_hi
            add("Nasdaq-Hoch ohne S&P", active, "warn" if active else "ok",
                f"Nasdaq-Hoch vor {_weeks_since_high(ndx)}W · S&P vor {_weeks_since_high(spx)}W",
                "Rally trägt nur auf Tech — typisch spät im Zyklus" if active
                else "Führung breit genug")

    # ---- 2) Yield curve 10Y - 3M ---------------------------------------------
    tnx, irx = g("^TNX"), g("^IRX")
    if tnx is not None and irx is not None:
        curve = (tnx - irx.reindex(tnx.index).ffill()).dropna()
        cur = float(curve.iloc[-1]); c13 = _diff(curve, 13)
        mn52 = float(curve.iloc[-52:].min())
        inverted = cur < 0
        resteep = (mn52 < 0) and (cur > mn52 + 0.5)     # +50bp off the trough
        lvl = "warn" if resteep else ("watch" if inverted else "ok")
        add("Zinskurve 10J−3M", resteep or inverted, lvl,
            f"{cur:+.2f} Pp · 13W {c13 * 100:+.0f} Bp · 52W-Tief {mn52:+.2f}",
            "Versteilerung AUS einer Inversion — historisch das Rezessions-Timing-Signal, "
            "nicht die Inversion selbst" if resteep else
            "invertiert — Warnstufe, Timing offen" if inverted else "normal")

    # ---- 3) Credit: HYG / IEF ------------------------------------------------
    hyg, ief = g("HYG"), g("IEF")
    if hyg is not None and ief is not None and spx is not None:
        ratio = (hyg / ief.reindex(hyg.index).ffill()).dropna()
        r13 = _chg(ratio, 13)
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        active = np.isfinite(r13) and r13 < -3.0 and spx_near
        add("Kreditspreads weiten sich", active, "warn" if active else
            ("watch" if np.isfinite(r13) and r13 < -3.0 else "ok"),
            f"HYG/IEF 13W {r13:+.1f}%" if np.isfinite(r13) else "n/a",
            "Kredit preist Stress, Aktien nicht — Kredit hat meist recht" if active
            else "Kredit schwächer, aber Index ebenfalls" if np.isfinite(r13) and r13 < -3
            else "kein Stress im Kreditmarkt")

    # ---- 4) Copper / Gold -------------------------------------------------------
    hg, gc = g("HG=F"), g("GC=F")
    if hg is not None and gc is not None:
        ratio = (hg / gc.reindex(hg.index).ffill()).dropna()
        r13 = _chg(ratio, 13)
        active = np.isfinite(r13) and r13 < -8.0
        add("Kupfer/Gold fällt", active, "warn" if active else "ok",
            f"13W {r13:+.1f}%" if np.isfinite(r13) else "n/a",
            "Wachstum verliert gegen Angst — Zykliker-Warnung" if active
            else "Wachstumsproxy intakt")

    # ---- 5) Dollar AND gold up ----------------------------------------------
    dxy = g("DX-Y.NYB")
    if dxy is not None and gc is not None:
        d13, g13 = _chg(dxy, 13), _chg(gc, 13)
        active = np.isfinite(d13) and np.isfinite(g13) and d13 > 3.0 and g13 > 5.0
        add("Dollar UND Gold steigen", active, "warn" if active else "ok",
            f"DXY 13W {d13:+.1f}% · Gold 13W {g13:+.1f}%",
            "beides zugleich = Flucht in Sicherheit, nicht Reflation" if active
            else "kein gleichzeitiger Safe-Haven-Zug")

    # ---- 6) Rate shock at highs ------------------------------------------------
    if tnx is not None and spx is not None:
        t13 = _diff(tnx, 13) * 100
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        active = np.isfinite(t13) and t13 > 50 and spx_near
        add("Zinsschock bei Höchstständen", active, "warn" if active else "ok",
            f"10J 13W {t13:+.0f} Bp",
            "Langfristzinsen laufen weg, während Aktien am Hoch stehen — Bewertungsdruck kommt "
            "mit Verzögerung" if active else "Zinsen kein akuter Gegenwind")

    # ---- 7) Long end vs 10Y (term premium) ----------------------------------
    tyx = g("^TYX")
    if tnx is not None and tyx is not None:
        t13 = _diff(tnx, 13) * 100; y13 = _diff(tyx, 13) * 100
        active = np.isfinite(t13) and np.isfinite(y13) and y13 - t13 > 15
        add("30J steigt schneller als 10J", active, "watch" if active else "ok",
            f"30J {y13:+.0f} Bp vs 10J {t13:+.0f} Bp (13W)",
            "Laufzeitprämie steigt — Fiskal-/Angebotsdruck am langen Ende" if active
            else "keine Auffälligkeit am langen Ende")

    # ---- 8) Yen squeeze (carry unwind) --------------------------------------
    jpy = g("JPY=X")
    if jpy is not None:
        j4 = _chg(jpy, 4)
        active = np.isfinite(j4) and j4 < -4.0
        add("Yen-Squeeze", active, "warn" if active else "ok",
            f"USD/JPY 4W {j4:+.1f}%",
            "schnelle Yen-Aufwertung = Carry-Trade-Abbau, trifft Risikoassets global "
            "(vgl. Aug 2024)" if active else "Yen ruhig")

    # ---- 9) Oil shock ----------------------------------------------------------
    cl = g("CL=F")
    if cl is not None:
        o13 = _chg(cl, 13)
        active = np.isfinite(o13) and abs(o13) > 20
        add("Ölpreis-Schock", active, "watch" if active else "ok",
            f"WTI 13W {o13:+.1f}%",
            ("Inflationsimpuls" if o13 > 0 else "Nachfrageeinbruch?") if active
            else "Öl im Rahmen")

    # ---- 10) VIX term structure --------------------------------------------
    vix, vix3 = g("^VIX"), g("^VIX3M")
    if vix is not None and vix3 is not None:
        v, v3 = float(vix.iloc[-1]), float(vix3.reindex(vix.index).ffill().iloc[-1])
        back = v > v3
        add("VIX-Terminstruktur", back, "warn" if back else "ok",
            f"VIX {v:.1f} vs VIX3M {v3:.1f} ({(v / v3 - 1) * 100:+.0f}%)",
            "Backwardation — Absicherung wird JETZT teurer als später bezahlt: akuter Stress"
            if back else "Contango, normal")
    if vix is not None and spx is not None:
        v4 = _chg(vix, 4)
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.97)
        active = np.isfinite(v4) and v4 > 30 and spx_near
        add("VIX steigt bei Höchstständen", active, "warn" if active else "ok",
            f"VIX 4W {v4:+.0f}%" if np.isfinite(v4) else "n/a",
            "Vola dreht, bevor der Index es tut — Sorglosigkeit bricht" if active
            else "Vola bestätigt den Index")

    # ---- 11) Bond volatility ------------------------------------------------
    move = g("^MOVE")
    if move is not None:
        m4 = _chg(move, 4)
        active = np.isfinite(m4) and m4 > 25
        add("Anleihe-Vola springt", active, "watch" if active else "ok",
            f"MOVE {float(move.iloc[-1]):.0f} · 4W {m4:+.0f}%" if np.isfinite(m4) else "n/a",
            "Unruhe im Zinsmarkt läuft dem Aktienmarkt meist voraus" if active
            else "Zinsmarkt ruhig")

    # ---- 12) Banks lead the credit cycle --------------------------------------
    kre = g("KRE")
    if kre is not None and spx is not None:
        ratio = (kre / spx.reindex(kre.index).ffill()).dropna()
        r13 = _chg(ratio, 13)
        active = np.isfinite(r13) and r13 < -8.0
        add("Regionalbanken fallen zurück", active, "warn" if active else "ok",
            f"KRE/SPX 13W {r13:+.1f}%" if np.isfinite(r13) else "n/a",
            "Banken preisen Kreditstress vor dem Markt (vgl. März 2023)" if active
            else "Banken laufen mit")

    # ---- 13) Defensive rotation ---------------------------------------------
    xlp, xly = g("XLP"), g("XLY")
    if xlp is not None and xly is not None and spx is not None:
        ratio = (xlp / xly.reindex(xlp.index).ffill()).dropna()
        r13 = _chg(ratio, 13)
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        rot = np.isfinite(r13) and r13 > 5.0
        add("Rotation in Defensive", rot, ("warn" if rot and spx_near else "watch" if rot else "ok"),
            f"Staples/Discretionary 13W {r13:+.1f}%" if np.isfinite(r13) else "n/a",
            "Geld wandert in Staples, während der Index noch am Hoch steht — späte Phase"
            if rot and spx_near else "Defensiv-Rotation läuft" if rot else "Risk-on intakt")

    # ---- 14) Quality spread inside credit ------------------------------------
    lqd = g("LQD")
    if hyg is not None and lqd is not None:
        ratio = (hyg / lqd.reindex(hyg.index).ffill()).dropna()
        r13 = _chg(ratio, 13)
        active = np.isfinite(r13) and r13 < -3.0
        add("High Yield fällt gegen Investment Grade", active, "watch" if active else "ok",
            f"HYG/LQD 13W {r13:+.1f}%" if np.isfinite(r13) else "n/a",
            "Schwache Schuldner werden zuerst gemieden" if active else "kein Qualitätsflucht")

    # ---- 15) Inflation expectations -----------------------------------------
    tip = g("TIP")
    if tip is not None and ief is not None:
        ratio = (tip / ief.reindex(tip.index).ffill()).dropna()
        r13 = _chg(ratio, 13)
        active = np.isfinite(r13) and r13 > 2.0
        add("Inflationserwartung steigt", active, "watch" if active else "ok",
            f"TIP/IEF 13W {r13:+.1f}%" if np.isfinite(r13) else "n/a",
            "Breakevens ziehen an — Zinssenkungen werden unwahrscheinlicher" if active
            else "Inflationserwartung stabil")

    # ---- 16) Bitcoin as liquidity canary --------------------------------------
    btc = g("BTC-USD")
    if btc is not None and spx is not None:
        bs = btc.rolling(C.MA_WEEKS).mean()
        b_st = classify_stage(float(btc.iloc[-1]), float(bs.iloc[-1]),
                              float(I.sma_slope(bs).iloc[-1]))
        ss_ = spx.rolling(C.MA_WEEKS).mean()
        s_st = classify_stage(float(spx.iloc[-1]), float(ss_.iloc[-1]),
                              float(I.sma_slope(ss_).iloc[-1]))
        active = b_st == 4 and s_st == 2
        add("Bitcoin bricht, Aktien nicht", active, "watch" if active else "ok",
            f"BTC {STAGE_NAME[b_st]} · S&P {STAGE_NAME[s_st]}",
            "das liquiditätssensitivste Asset dreht zuerst — Divergenz beobachten"
            if active else "kein Liquiditätswarnsignal")

    n_warn = sum(1 for s in signals if s["active"] and s["level"] == "warn")
    n_watch = sum(1 for s in signals if s["active"] and s["level"] == "watch")
    order = {"Aktien": 0, "Volatilität": 1, "Zinsen": 2, "Kredit": 3, "Rotation": 4,
             "FX": 5, "Rohstoffe": 6, "Liquidität": 7}
    rows.sort(key=lambda r: (order.get(r["group"], 9), r["symbol"]))
    return {"rows": rows, "signals": signals,
            "n_warn": n_warn, "n_watch": n_watch}
