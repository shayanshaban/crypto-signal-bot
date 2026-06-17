"""
config.py — Central configuration for the crypto signal bot.

Edit values here; nothing else in the project needs changing.
"""

# ── Trading symbol ───────────────────────────────────────────────────────────
# LBank uses underscore format; Wallex / display uses uppercase concatenated.
SYMBOL_LBANK   = "btc_usdt"       # format required by LBank API
SYMBOL_DISPLAY = "BTCUSDT"        # used in prompts and log output

# ── LBank API endpoints ──────────────────────────────────────────────────────
LBANK_KLINE_URL  = "https://api.lbkex.com/v2/kline.do"
LBANK_TICKER_URL = "https://api.lbkex.com/v2/supplement/ticker/price.do"

# ── Wallex API endpoint (alternative / legacy data source) ───────────────────
WALLEX_KLINE_URL = "https://api.wallex.ir/v1/udf/history"

# ── DeepSeek browser automation ─────────────────────────────────────────────
DEEPSEEK_URL     = "https://chat.deepseek.com/"
BOT_PROFILE_DIR  = "./bot_profile"   # persistent Chromium profile with saved login
DEEPSEEK_MODE    = "Expert"          # radio button name on the DeepSeek UI

# ── Timeouts (seconds) ───────────────────────────────────────────────────────
BROWSER_LAUNCH_TIMEOUT   = 60_000   # ms  — Playwright timeout for browser launch
PAGE_LOAD_TIMEOUT        = 30_000   # ms
SELECTOR_TIMEOUT         = 10_000   # ms
RESPONSE_START_TIMEOUT   = 360_000  # ms  — wait for first assistant token
RESPONSE_STABLE_TIMEOUT  = 90       # sec — wait_for_response outer loop
RESPONSE_STABLE_CHECKS   = 3        # consecutive equal-text checks = "done"
RETRY_ATTEMPTS           = 3        # retries on connect failure
RETRY_DELAY_SEC          = 5        # seconds between retries

# ── File paths ───────────────────────────────────────────────────────────────
PROMPT_FILE  = "prompts/trader.txt"
OUTPUT_FILE  = "output/market_data.txt"   # assembled prompt + market data
LOG_FILE     = "logs/signals.log"

# ── Candle counts per timeframe ──────────────────────────────────────────────
CANDLES = {
    "month1":    {"tf_minutes": 43_200, "count": 24},
    "week1":     {"tf_minutes": 10_080, "count": 52},
    "day1":      {"tf_minutes":  1_440, "count": 120},
    "hour4":     {"tf_minutes":    240, "count": 120},
    "minute15":  {"tf_minutes":     15, "count": 120},
}

# Preferred / display names for each LBank timeframe key
TIMEFRAME_LABELS = {
    "month1":   "1M",
    "week1":    "1W",
    "day1":     "1D",
    "hour4":    "4H",
    "minute15": "15Min",
}
