# Crypto Signal Bot

An automated crypto trading signal generator that:
1. Pulls multi-timeframe OHLCV candle data from **LBank**
2. Assembles it into a structured prompt
3. Sends the prompt to **DeepSeek** (via browser automation)
4. Parses and logs the JSON trading signal

---

## Project Layout

```
crypto-signal-bot/
├── config.py              ← all configurable values live here
├── main.py                ← entry point
├── setup_browser.py       ← one-time login helper
├── requirements.txt
│
├── src/
│   ├── data_fetcher.py    ← LBank + Wallex API wrappers
│   └── deepseek_client.py ← Playwright browser automation
│
├── prompts/
│   └── trader.txt         ← system prompt sent to DeepSeek
│
├── output/                ← assembled prompt + market data (git-ignored)
└── logs/                  ← trading signal log (git-ignored)
```

---

## Quick Start

### 1 — Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2 — Configure

Open **`config.py`** and adjust:

| Setting | Default | What it controls |
|---|---|---|
| `SYMBOL_LBANK` | `"btc_usdt"` | Trading pair (LBank format) |
| `SYMBOL_DISPLAY` | `"BTCUSDT"` | Trading pair (display / Wallex format) |
| `BOT_PROFILE_DIR` | `"./bot_profile"` | Where Chrome saves your DeepSeek login |
| `DEEPSEEK_MODE` | `"Expert"` | DeepSeek chat mode radio button |
| `OUTPUT_FILE` | `"output/market_data.txt"` | Assembled prompt written here |
| `LOG_FILE` | `"logs/signals.log"` | Signals appended here |

### 3 — Log in to DeepSeek (once)

```bash
python setup_browser.py
```

A real Chrome window opens. Log in manually, then press Enter in the terminal.
Your session is saved to `bot_profile/` and reused on every subsequent run.

### 4 — Get a signal

```bash
python main.py
```

Output example:

```json
{
  "symbol": "BTCUSDT",
  "position": "SHORT",
  "confidence": 85,
  "entry": 65715.61,
  "stop_loss": 65920.00,
  "take_profit": 65300.00,
  "risk_reward": 2.03,
  "reason": "1M bearish breaking May low; 1D strong rejection at 67295 …"
}
```

---

## Data Sources

| Source | Used for | Endpoint |
|---|---|---|
| LBank | Primary (multi-TF candles + ticker) | `api.lbkex.com` |
| Wallex | Alternative (60-min candles, spot check) | `api.wallex.ir` |

Both are public REST APIs — no API key required.

---

## Customising the Prompt

Edit **`prompts/trader.txt`** to change the AI's instructions, output schema,
or analysis process.  The file is loaded fresh on every `main.py` run.

---

## Notes

- `bot_profile/` is git-ignored because it contains browser session cookies.
- `output/` and `logs/` are git-ignored; their `.gitkeep` files preserve the
  folder structure in the repository.
- DeepSeek's UI selectors (`div.ds-assistant-message-main-content`) may change
  with site updates — adjust in `src/deepseek_client.py` if responses stop
  being captured.
