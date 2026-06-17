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
LBANK_KLINE_URL  = "https://api.lbkex.com/v2/kline.do"
LBANK_TICKER_URL = "https://api.lbkex.com/v2/supplement/ticker/price.do"

WALLEX_KLINE_URL = "https://api.wallex.ir/v1/udf/history"   # alternative / spot-check


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. AI Provider — DeepSeek (browser automation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEEPSEEK_URL    = "https://chat.deepseek.com/"
BOT_PROFILE_DIR = str(ROOT / "bot_profile")  # persists login session
DEEPSEEK_MODE   = "Expert"                   # radio-button label in the UI

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
DB_FILE = str(ROOT / "logs" / "bot.db")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Signal Rules
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MIN_CONFIDENCE = 60   # signals with lower confidence are skipped


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. File Paths
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROMPT_FILE = str(ROOT / "prompts" / "trader.txt")
OUTPUT_FILE = str(ROOT / "output"  / "market_data.txt")
LOG_FILE    = str(ROOT / "logs"    / "signals.log")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. Timeframes & Candles
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CANDLES = {
    "month1":   {"tf_minutes": 43_200, "count": 24},
    "week1":    {"tf_minutes": 10_080, "count": 52},
    "day1":     {"tf_minutes":  1_440, "count": 120},
    "hour4":    {"tf_minutes":    240, "count": 120},
    "minute15": {"tf_minutes":     15, "count": 120},
}

TIMEFRAME_LABELS = {
    "month1":   "1M",
    "week1":    "1W",
    "day1":     "1D",
    "hour4":    "4H",
    "minute15": "15Min",
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
