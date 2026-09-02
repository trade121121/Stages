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
from .market import classify_stage, stage_of, STAGE_NAME


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


def _dual(ratio: pd.Series, thr13: float, thr4: float) -> tuple[bool, str, float, float]:
    """Change over 4 AND 13 weeks; active if EITHER crosses its threshold
    (same sign as the thresholds). 4W reacts to sharp moves, 13W to slow
    grinds. Returns (active, text, chg4, chg13)."""
    c4, c13 = _chg(ratio, 4), _chg(ratio, 13)
    neg = thr13 < 0
    hit4 = np.isfinite(c4) and (c4 < thr4 if neg else c4 > thr4)
    hit13 = np.isfinite(c13) and (c13 < thr13 if neg else c13 > thr13)
    txt = (f"4W {c4:+.1f}% · 13W {c13:+.1f}%"
           if np.isfinite(c4) and np.isfinite(c13) else "n/a")
    return bool(hit4 or hit13), txt, c4, c13


def _weeks_since_high(s: pd.Series, window: int = 52) -> int:
    w = s.dropna().iloc[-window:]
    if len(w) < 3:
        return 999
    return int(len(w) - 1 - int(np.argmax(w.values)))


def _row(sym: str, wk: pd.DataFrame, is_yield: bool) -> dict:
    c = wk["close"]
    st = stage_of(c)
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
                               (djt, "Dow Transports", "Dow-Theorie: Transports bestätigen nicht")):
            if proxy is None:
                continue
            p_hi = _weeks_since_high(proxy) <= 8
            active = spx_hi and not p_hi
            add(f"S&P-Hoch ohne {nm}", active, "warn" if active else "ok",
                f"S&P-Hoch vor {_weeks_since_high(spx)}W · {nm}-Hoch vor {_weeks_since_high(proxy)}W",
                txt if active else f"{nm} bestätigt")
    # ---- 1b) The three majors must confirm each other (weekly closes) -----
    trio = {"S&P": spx, "Nasdaq": ndx, "Dow": dji}
    ages = {k: _weeks_since_high(v) for k, v in trio.items() if v is not None}
    if len(ages) == 3:
        fresh = {k for k, a in ages.items() if a <= 4}
        stale = {k for k, a in ages.items() if a > 8}
        active = 1 <= len(fresh) <= 2 and len(stale) >= 1
        worst = max(ages.values())
        add("Index-Divergenz S&P / Nasdaq / Dow", active,
            "warn" if active and worst > 13 else "watch" if active else "ok",
            " · ".join(f"{k}-Hoch vor {a}W" for k, a in ages.items()),
            (f"{', '.join(sorted(fresh))} auf neuem Hoch, "
             f"{', '.join(sorted(stale))} nicht — Dow-Theorie: unbestätigte Bewegung")
            if active else "alle drei bestätigen einander"
            if len(fresh) == 3 else "keiner am Hoch — keine Divergenz, sondern Korrektur")

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
        hit, txt, _, _ = _dual(ratio, -3.0, -1.5)
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        add("Kreditspreads weiten sich", hit,
            "warn" if hit and spx_near else "watch" if hit else "ok",
            "HYG/IEF " + txt,
            "Kredit preist Stress, Aktien nicht — Kredit hat meist recht" if hit and spx_near
            else "Kredit schwächer, Index ebenfalls" if hit else "kein Stress im Kreditmarkt")

    # ---- 4) Copper / Gold -------------------------------------------------------
    hg, gc = g("HG=F"), g("GC=F")
    if hg is not None and gc is not None:
        ratio = (hg / gc.reindex(hg.index).ffill()).dropna()
        active, txt, _, _ = _dual(ratio, -8.0, -5.0)
        add("Kupfer/Gold fällt", active, "warn" if active else "ok", txt,
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
        t4, t13 = _diff(tnx, 4) * 100, _diff(tnx, 13) * 100
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        hit = (np.isfinite(t4) and t4 > 30) or (np.isfinite(t13) and t13 > 50)
        active = hit and spx_near
        add("Zinsschock bei Höchstständen", active, "warn" if active else "ok",
            f"10J 4W {t4:+.0f} Bp · 13W {t13:+.0f} Bp",
            "Langfristzinsen laufen weg, während Aktien am Hoch stehen — Bewertungsdruck kommt "
            "mit Verzögerung" if active else "Zinsen kein akuter Gegenwind")

    # ---- 7) Long end vs 10Y (term premium) ----------------------------------
    tyx = g("^TYX")
    if tnx is not None and tyx is not None:
        t4 = _diff(tnx, 4) * 100; y4 = _diff(tyx, 4) * 100
        active = np.isfinite(t4) and np.isfinite(y4) and y4 - t4 > 10
        add("30J steigt schneller als 10J", active, "watch" if active else "ok",
            f"30J {y4:+.0f} Bp vs 10J {t4:+.0f} Bp (4W)",
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
        o4, o13 = _chg(cl, 4), _chg(cl, 13)
        active = (np.isfinite(o4) and abs(o4) > 12) or (np.isfinite(o13) and abs(o13) > 20)
        ref = o4 if np.isfinite(o4) and abs(o4) > 12 else o13
        add("Ölpreis-Schock", active, "watch" if active else "ok",
            f"WTI 4W {o4:+.1f}% · 13W {o13:+.1f}%",
            ("Inflationsimpuls" if ref > 0 else "Nachfrageeinbruch?") if active
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
        active, txt, _, _ = _dual(ratio, -8.0, -5.0)
        add("Regionalbanken fallen zurück", active, "warn" if active else "ok",
            "KRE/SPX " + txt,
            "Banken preisen Kreditstress vor dem Markt (vgl. März 2023)" if active
            else "Banken laufen mit")

    # ---- 13) Defensive rotation ---------------------------------------------
    xlp, xly = g("XLP"), g("XLY")
    if xlp is not None and xly is not None and spx is not None:
        ratio = (xlp / xly.reindex(xlp.index).ffill()).dropna()
        rot, txt, _, _ = _dual(ratio, 5.0, 3.0)
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        add("Rotation in Defensive", rot, ("warn" if rot and spx_near else "watch" if rot else "ok"),
            "Staples/Discretionary " + txt,
            "Geld wandert in Staples, während der Index noch am Hoch steht — späte Phase"
            if rot and spx_near else "Defensiv-Rotation läuft" if rot else "Risk-on intakt")

    # ---- 14) Quality spread inside credit ------------------------------------
    lqd = g("LQD")
    if hyg is not None and lqd is not None:
        ratio = (hyg / lqd.reindex(hyg.index).ffill()).dropna()
        active, txt, _, _ = _dual(ratio, -3.0, -1.5)
        add("High Yield fällt gegen Investment Grade", active, "watch" if active else "ok",
            "HYG/LQD " + txt,
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
        b4 = _chg(btc, 4)
        spx_near = bool(spx.iloc[-1] >= spx.iloc[-52:].max() * 0.95)
        hit = np.isfinite(b4) and b4 < -15.0
        add("Bitcoin fällt scharf", hit, "warn" if hit and spx_near else "watch" if hit else "ok",
            f"BTC 4W {b4:+.1f}%" if np.isfinite(b4) else "n/a",
            "das liquiditätssensitivste Asset gibt nach, Aktien noch nicht — Divergenz"
            if hit and spx_near else "Liquidität zieht sich zurück" if hit
            else "kein Liquiditätswarnsignal")

    n_warn = sum(1 for s in signals if s["active"] and s["level"] == "warn")
    n_watch = sum(1 for s in signals if s["active"] and s["level"] == "watch")
    order = {"Aktien": 0, "Volatilität": 1, "Zinsen": 2, "Kredit": 3, "Rotation": 4,
             "FX": 5, "Rohstoffe": 6, "Liquidität": 7}
    rows.sort(key=lambda r: (order.get(r["group"], 9), r["symbol"]))
    return {"rows": rows, "signals": signals,
            "n_warn": n_warn, "n_watch": n_watch}
