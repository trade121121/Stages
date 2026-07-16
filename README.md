# Weinstein Weekly Screener

Stage-Analyse-Screener nach Stan Weinstein auf Wochenbasis mit Mansfield
Relative Strength. Läuft sonntags 07:00 UTC via GitHub Actions, Ergebnis
ist ein statisches Dashboard unter `docs/index.html` (GitHub Pages).

## Universen
- S&P 500 + Nasdaq-100 (Wikipedia, zur Laufzeit)
- STOXX Europe 600 (iShares-EXSA-Holdings; Fallback: `data/stoxx600_fallback.csv`)
- Eigene Watchlists (`watchlists.yaml`) mit Dual-MRS (lokaler Index + Themen-ETF)
- Sektor-Rotation: 11 GICS-ETFs + Themen-ETFs, MRS gegen SPX

## Scanner-Logik (alles weekly)
**Long (Stage 1→2):** Wochenschluss = 26W-Hoch, max. 10 % über Basis-Top ·
Kurs > 30W-SMA · SMA-Steigung (6W) > 0, war zuvor flach · MRS > 0
(frischer Nulllinien-Cross = Score-Bonus) · Basis: ≥ 13 Wochen seit 52W-Tief
und ≥ 2 Kurs/SMA-Crossings in 26W (V-Reversal-Filter) · Volumen ≥ 1,5× 10W-Ø
(Pflicht). Volatile Basen erhöhen den Score (Weinstein: wilde Basen laufen mehr).

**Short (Stage 3→4):** Wochenschluss = 26W-Tief · Kurs < 30W-SMA ·
SMA-Steigung ≤ 0 · MRS < 0 (RS-Divergenz = Bonus) · vorheriger Stage-2-Markup
≥ 1,5× innerhalb 156 Wochen (filtert Dauerverlierer). Volumen ist beim
Breakdown **kein Filter**, nur Bonus-Flag — Aktien fallen unter ihrem
eigenen Gewicht.

## Setup
1. Repo anlegen, Dateien pushen.
2. Settings → Pages → Source: `main` / `docs`.
3. Settings → Actions → Workflow permissions: **Read and write**.
4. `watchlists.yaml` mit eigenen Tickern füllen (China-Robotics!).
5. Erster Lauf manuell: Actions → weekly-screener → Run workflow.

## Bekannte Kanten
- STOXX-600-Quelle (iShares-CSV-URL) kann sich ändern → Fallback greift,
  Hinweis erscheint im Dashboard unter „Daten-Hinweise".
- yfinance-Ticker-Sonderfälle (BRK-B etc.) werden gemappt; Ausfälle werden
  gelistet, nie stumm verworfen.
- SKHY hat erst seit Juli 2026 Historie → fällt unter MIN_WEEKS_REQUIRED,
  taucht erst nach ~2,5 Jahren im Hauptscan auf (Watchlist zeigt ihn trotzdem
  mit MRS, sobald 52 Wochen erreicht sind).
