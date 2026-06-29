"""
config.py — Central configuration.

Sections:
  1. Trading Symbols
  2. Data Sources  (LBank, Wallex)
  3. AI Provider   (DeepSeek)
  4. Database
  5. Signal Rules
  6. File Paths
  7. Timeframes & Candles
  8. BackTester Setting
  ── Future (commented stubs) ──
  8. Exchange Execution
  9. Notifications
  10. Scheduler
"""

from pathlib import Path

ROOT = Path(__file__).parent   # project root, usable in path builds


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Trading Symbols
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYMBOL_LBANK   = "btc_usdt"   # LBank format  (underscore, lowercase)
SYMBOL_DISPLAY = "BTCUSDT"    # Display / prompt format


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Data Sources
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# https://www.lbkex.net/

# https://api.lbkex.com/

# https://api.lbank.info/

LBANK_KLINE_URL  = "https://api.lbank.info/v2/kline.do"
LBANK_TICKER_URL = "https://api.lbank.info/v2/supplement/ticker/price.do"

WALLEX_KLINE_URL = "https://api.wallex.ir/v1/udf/history"   # alternative / spot-check


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. AI Provider — DeepSeek (browser automation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEEPSEEK_URL    = "https://chat.deepseek.com/"
BOT_PROFILE_DIR = str(ROOT / "bot_profile")  # persists login session
DEEPSEEK_MODE   = "Expert"                   # radio-button label in the UI
BOT_STORAGE_STATE = "bot_storage_state.json"
HEAD_LESS_MODE = False               # if true browser won't popup 
# Timeouts — all in milliseconds unless noted
BROWSER_LAUNCH_TIMEOUT  = 60_000    # ms
PAGE_LOAD_TIMEOUT       = 30_000    # ms
SELECTOR_TIMEOUT        = 10_000    # ms
RESPONSE_START_TIMEOUT  = 360_000   # ms — wait for first token
RESPONSE_STABLE_TIMEOUT = 90        # seconds — outer polling loop
RESPONSE_STABLE_CHECKS  = 3         # consecutive equal-text polls = "done"
RETRY_ATTEMPTS          = 3
RETRY_DELAY_SEC         = 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Database
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DB_FILE = str(ROOT / "logs" / "MianDB.db")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Signal Rules
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MIN_CONFIDENCE = 60   # signals with lower confidence are skipped


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. File Paths
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROMPT_FILE = str(ROOT / "prompts" / "confirmer_v1.txt")
OUTPUT_FILE = str(ROOT / "output"  / "market_data.txt")
LOG_FILE    = str(ROOT / "logs"    / "signals.log")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. Timeframes & Candles
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRADING_TIME_FRAME = "minute15"

CANDLES = {
    "month1":   {"tf_minutes": 43_200, "count": 24, "raw": False, "raw_and_bake": False},
    "week1":    {"tf_minutes": 10_080, "count": 200, "raw": False, "raw_and_bake": False},
    "day1":     {"tf_minutes":  1_440, "count": 250, "raw": False, "raw_and_bake": False},
    "hour4":    {"tf_minutes":    240, "count": 250, "raw": False, "raw_and_bake": False},
    "minute15": {"tf_minutes":     15, "count": 120, "raw": True, "raw_and_bake": True},
}

TIMEFRAME_LABELS = {
    "month1":   "1M",
    "week1":    "1W",
    "day1":     "1D",
    "hour4":    "4H",
    "minute15": "15Min",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. BackTester Setting
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BACK_TEST_THREAD = 5    # The Concurency of back testing

BACK_TEST_WAIT_AFTER_ASK_AI = 10

BACK_TEST_CANDLES = {
    "month1":   {"tf_minutes": 43_200, "count": 36, "raw": False, "raw_and_bake": False},
    "week1":    {"tf_minutes": 10_080, "count": 150, "raw": False, "raw_and_bake": False},
    "day1":     {"tf_minutes":  1_440, "count": 2000, "raw": False, "raw_and_bake": False},
    "hour4":    {"tf_minutes":    240, "count": 2000, "raw": False, "raw_and_bake": False},
    "minute15": {"tf_minutes":     15, "count": 2000, "raw": True, "raw_and_bake": True},
}

BACK_TEST_CHART_OUTPUT_FILE = str(ROOT / "output" / "backtest_chart.html")

BACK_TEST_WARMUP_TRIM     = 500        # Trim base line to prevent out index error for historical data
BACK_TEST_STATE_FILES = [str(ROOT / "data" / "back_test" / f"state_{i}.json") for i in range(BACK_TEST_THREAD)]

BACK_TEST_OUTPUT_FILES = []

for i in range(BACK_TEST_THREAD):
    BACK_TEST_OUTPUT_FILES.append(
        str(ROOT / "output" / f"market_data_{i}.txt")
    )

IMPORT_DATA_FOLDER_DIR = str(ROOT / "historical_data")

# Rule Engine
MIN_ATR_THRESHOLD = 0.01
MIN_VOLUME_RATIO = 1.5
TREND_ALIGNMENT_REQUIRED = True

# Triple Barrier
MAX_HOLDING_BARS = 120

# Dataset
DATASET_DIR = str(ROOT / "dataset")
MODEL_SAVE_PATH = str(ROOT / "models")

FEUTURES = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
    "change_pct": "Change %",
    "period_high": "Period high",
    "period_low": "Period low",
    "position_in_period_range": "Position in period range",

    "ema9": "EMA9",
    "ema21": "EMA21",
    "ema50": "EMA50",
    "ema200": "EMA200",

    "price_vs_ema9": "Price vs EMA9",
    "price_vs_ema21": "Price vs EMA21",
    "price_vs_ema50": "Price vs EMA50",
    "price_vs_ema200": "Price vs EMA200",

    "ema_alignment": "EMA alignment",
    "ema50_vs_ema200": "EMA50 vs EMA200",

    "rsi": "RSI(14)",
    "rsi_zone": "RSI zone",

    "stoch_rsi": "Stoch RSI",
    "stoch_rsi_zone": "Stoch RSI zone",

    "macd_line": "MACD line",
    "macd_signal": "MACD signal",
    "macd_histogram": "MACD histogram",
    "macd_position": "MACD position",
    "macd_cross": "MACD cross",

    "bb_upper": "BB upper",
    "bb_mid": "BB mid",
    "bb_lower": "BB lower",
    "bb_width_pct": "BB width %",
    "bb_position": "BB position",
    "bb_signal": "BB signal",
    "bb_squeeze": "BB squeeze",

    "atr14": "ATR(14)",
    "atr_pct_price": "ATR % price",

    "volume_avg20": "Volume avg(20)",
    "volume_ratio": "Volume ratio",
    "volume_signal": "Volume signal",
    "volume_trend": "Volume trend",

    "obv_trend": "OBV trend",

    "market_structure": "Market structure",

    "candle_type": "Candle type",
    "engulfing": "Engulfing",
    "last_3_candles": "Last 3 candles",

    "distance_to_support_pct": "Distance to support %",
    "distance_to_resistance_pct": "Distance to resistance %",

    "timestamp": "Timestamp",
    "candle_id": "id",
    "ema9_slope": "EMA9 slope",
    "ema21_slope": "EMA21 slope",
    "ema50_slope": "EMA50 slope",
    "ema200_slope": "EMA200 slope",

    "rsi_slope": "RSI slope",

    "stoch_rsi_slope": "Stoch RSI slope",

    "return_1": "Return 1",
    "return_3": "Return 3",
    "return_5": "Return 5",
    "return_10": "Return 10",
    "return_20": "Return 20",

    "volatility_10": "Volatility 10",
    "volatility_20": "Volatility 20",

    "highest_20": "Highest 20",
    "lowest_20": "Lowest 20",

    "distance_highest20": "Distance Highest20",
    "distance_lowest20": "Distance Lowest20",

    "body_pct": "Body %",
    "upper_wick_pct": "Upper wick %",
    "lower_wick_pct": "Lower wick %",

    "prev_high_dist": "Prev High Dist",
    "prev_low_dist": "Prev Low Dist",

    "bull_ratio_10": "Bull Ratio 10",
    "avg_body10": "Avg Body10",

    "close_position": "Close Position",

    "hour": "Hour",
    "day_of_week": "Day of Week",
    "session": "Session",

    "trend_age": "Trend age",
    "bars_since_ema_cross": "Bars Since EMA Cross",
    "ema9_vs_ema21": "EMA9 vs EMA21",

    "distance_last_swing_high": "Distance Last Swing High",
    "distance_last_swing_low": "Distance Last Swing Low",
}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. Exchange Execution  [FUTURE — uncomment when ready]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXCHANGE           = "lbank"           # or "binance", "bybit" …
# EXCHANGE_API_KEY   = ""                # load from .env in production
# EXCHANGE_SECRET    = ""
# TRADE_SIZE_USDT    = 100               # fixed USDT per trade
# MAX_OPEN_POSITIONS = 1
# LEVERAGE           = 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. Notifications  [FUTURE — uncomment when ready]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM_TOKEN   = ""                  # load from .env
# TELEGRAM_CHAT_ID = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 10. Scheduler  [FUTURE — uncomment when ready]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RUN_INTERVAL_MIN = 15    # how often to check for signals
