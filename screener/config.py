"""Central configuration for the Weinstein weekly screener."""

# ---------------------------------------------------------------------------
# Benchmarks (yfinance symbols)
# ---------------------------------------------------------------------------
BENCH_US = "^GSPC"        # S&P 500
BENCH_EU = "^STOXX"       # STOXX Europe 600
BENCH_HK = "^HSI"         # Hang Seng

# ---------------------------------------------------------------------------
# Sector / theme rotation view: everything is measured against BENCH_US
# ---------------------------------------------------------------------------
SECTOR_ETFS = {
    # GICS sectors
    "XLK": "Technology", "XLE": "Energy", "XLF": "Financials",
    "XLV": "Health Care", "XLI": "Industrials", "XLY": "Cons. Discretionary",
    "XLP": "Cons. Staples", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real Estate", "XLC": "Communication",
    # Themes
    "IGV": "Software", "BOTZ": "Robotics/AI", "SOXX": "Semis",
    "SMH": "Semis (SMH)", "URA": "Uranium", "GDX": "Gold Miners",
    "XME": "Metals & Mining", "ITA": "Defense", "KWEB": "China Internet",
    "^HSI": "Hang Seng (Index)",
}

# ---------------------------------------------------------------------------
# Indicator parameters (all on WEEKLY bars)
# ---------------------------------------------------------------------------
MA_WEEKS = 30                 # Weinstein 30-week SMA
MRS_WEEKS = 52                # Mansfield RS normalisation window
SLOPE_LOOKBACK = 6            # SMA slope measured vs. 6 weeks ago
VOL_AVG_WEEKS = 10            # volume baseline
BREAKOUT_WINDOW = 26          # new 26-week closing high/low
MRS_FRESH_CROSS_WEEKS = 8     # "fresh" zero-line cross window

# ---------------------------------------------------------------------------
# Long scanner (Stage 1 -> 2)
# ---------------------------------------------------------------------------
LONG_MIN_BASE_WEEKS = 13          # min weeks between 52w low and breakout
LONG_MIN_MA_CROSSINGS = 2         # price/SMA30 crossings in last 26w
LONG_FLAT_SLOPE_ABS = 0.03        # |6w slope| below this = "flattened" MA
LONG_FLAT_LOOKBACK = 20           # MA must have been flat within last N weeks
LONG_MAX_EXT_OVER_BASE = 0.20     # breakout close max 20% above prior 26w max
LONG_MIN_VOL_RATIO = 1.5          # volume confirmation vs 10w average ...
BREAKOUT_VOL_LOOKBACK = 4         # ... required in any of the last N weeks

# Pre-breakout (still inside the base, coiling under the range high)
PREB_MAX_BELOW_HIGH = 0.05        # within 5% below the 26w range high
PREB_MIN_MRS = -5.0               # RS may be slightly negative if improving
PREB_MAX_ABS_SLOPE = 0.04         # MA must be flat NOW, not just historically
PREB_MAX_EXT_OVER_MA = 0.15       # price max 15% above the flat MA

# Base-low entries (accumulation-range style, RS-disambiguated)
BL_MAX_RANGE_POS = 0.33           # price in lower third of the 26w range
BL_MIN_LOW_AGE = 8                # 52w low must be at least N weeks old
BL_MIN_MRS_CHG8 = 0.0             # MRS must be improving over 8 weeks
BL_MIN_MRS = -20.0                # but not a total laggard

# Long pullback entry (Stage 2 continuation: retest of rising 30W MA)
PB_MAX_EXT_OVER_MA = 0.08         # buy zone: within 8% above the 30W MA
PB_MIN_OFF_HIGH = 0.03            # pulled back at least 3% from recent high
PB_MIN_SLOPE = 0.005              # MA must be clearly rising
PB_HIGH_WINDOW = 13               # 26w high must have been made in last N weeks

# ---------------------------------------------------------------------------
# Short scanner (Stage 3 -> 4)
# ---------------------------------------------------------------------------
SHORT_MIN_PRIOR_MARKUP = 1.5      # markup factor low -> high
SHORT_MARKUP_LOOKBACK = 156       # weeks to search for the prior Stage-2 move
SHORT_VOL_BONUS_RATIO = 1.5       # volume on breakdown = bonus flag, NOT filter

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
HISTORY_PERIOD = "4y"             # enough for 52w MRS + prior-markup lookback
MIN_WEEKS_REQUIRED = 120          # skip tickers with less history
BATCH_SIZE = 100                  # yfinance batch download size
MAX_RETRIES = 3

# yfinance suffix mapping for iShares STOXX600 holdings exchanges
EXCHANGE_SUFFIX = {
    "Xetra": ".DE", "Deutsche Boerse Ag": ".DE", "Boerse Berlin": ".BE",
    "London Stock Exchange": ".L", "Euronext Amsterdam": ".AS",
    "Euronext Paris": ".PA", "Euronext Brussels": ".BR",
    "Euronext Lisbon": ".LS", "Euronext Milan": ".MI",
    "Borsa Italiana": ".MI", "SIX Swiss Exchange": ".SW",
    "Nasdaq Omx Helsinki Ltd.": ".HE", "Nasdaq Omx Stockholm": ".ST",
    "Nasdaq Omx Copenhagen": ".CO", "Oslo Bors": ".OL",
    "Wiener Boerse Ag": ".VI", "Bolsa De Madrid": ".MC",
    "Irish Stock Exchange - All Market": ".IR", "Euronext Dublin": ".IR",
    "Warsaw Stock Exchange": ".WA",
}

ISHARES_STOXX600_CSV = (
    "https://www.ishares.com/de/privatanleger/de/produkte/251931/"
    "ishares-stoxx-europe-600-ucits-etf-de-fund/1478358465952.ajax"
    "?fileType=csv&fileName=EXSA_holdings&dataType=fund"
)

OUTPUT_DIR = "docs"
