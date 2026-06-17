"""
src/data_fetcher.py — Market data retrieval from LBank and Wallex.

Provides:
  fetch_data()   — assemble the full multi-timeframe prompt file (LBank)
  fetch_wallex() — fetch a single 60-minute candle series (Wallex)
"""

import time
import json
import requests

import config


# ── LBank helpers ────────────────────────────────────────────────────────────

def _get_candles(timeframe: str, tf_minutes: int, count: int) -> dict:
    """Return raw kline JSON from LBank for the given timeframe."""
    to_time   = int(time.time())
    from_time = to_time - (count * tf_minutes * 60)

    params = {
        "symbol": config.SYMBOL_LBANK,
        "size":   count,
        "type":   timeframe,
        "time":   from_time,
    }
    response = requests.get(config.LBANK_KLINE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _get_current_price() -> dict:
    """Return the latest ticker price from LBank."""
    params   = {"symbol": config.SYMBOL_LBANK}
    response = requests.get(config.LBANK_TICKER_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_data(PROMPT_FILE) -> None:
    """
    Pull multi-timeframe candle data from LBank and write the assembled
    prompt (system instructions + market data) to config.OUTPUT_FILE.
    """
    with open(config.OUTPUT_FILE, "w", encoding="utf-8") as out:

        # ── System prompt ────────────────────────────────────────────────────
        with open(PROMPT_FILE, "r", encoding="utf-8") as pf:
            out.write(pf.read())

        # ── Header ───────────────────────────────────────────────────────────
        out.write(f"Symbol : {config.SYMBOL_LBANK}\n")
        out.write(
            "Data-Format : "
            "[[Timestamp, Open Price, Highest Price, Lowest Price, Close Price, Trading Volume]]\n\n"
        )

        # ── Current price ────────────────────────────────────────────────────
        ticker = _get_current_price()
        out.write(f"Current Price : {ticker['data'][0]['price']}\n")
        out.write(f"Current Time Stamp : {ticker['ts']}\n\n")

        # ── Candles per timeframe ────────────────────────────────────────────
        for tf_key, tf_cfg in config.CANDLES.items():
            label = config.TIMEFRAME_LABELS[tf_key]
            data  = _get_candles(tf_key, tf_cfg["tf_minutes"], tf_cfg["count"])

            out.write(f"Time-Frame : {label}\n\n")
            for candle in data["data"]:
                out.write(str(candle) + "\n")
            out.write("\n")


# ── Wallex helper (alternative data source) ──────────────────────────────────

def fetch_wallex(symbol: str = config.SYMBOL_DISPLAY) -> list[dict]:
    """
    Fetch the last 100 hourly (60-minute) candles for *symbol* from
    the Wallex API and return them as a list of OHLCV dicts.
    """
    to_time   = int(time.time())
    from_time = to_time - (100 * 60 * 60)

    params = {
        "symbol":     symbol,
        "resolution": "60",
        "from":       from_time,
        "to":         to_time,
    }
    headers  = {"Content-Type": "application/json"}
    response = requests.get(
        config.WALLEX_KLINE_URL, params=params, headers=headers, timeout=30
    )
    response.raise_for_status()
    raw = response.json()

    candles = [
        {
            "timestamp": raw["t"][i],
            "open":      float(raw["o"][i]),
            "high":      float(raw["h"][i]),
            "low":       float(raw["l"][i]),
            "close":     float(raw["c"][i]),
            "volume":    float(raw["v"][i]),
        }
        for i in range(len(raw["t"]))
    ]
    return candles


# ── Quick CLI smoke-test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Fetching Wallex 60M candles …")
    candles = fetch_wallex()
    print(f"Symbol : {config.SYMBOL_DISPLAY}")
    print("Time-Frame : 60M")
    print(json.dumps(candles[-3:], indent=2))   # show last 3 candles only

    print("\nFetching LBank multi-TF data …")
    fetch_data()
    print(f"Done — output written to {config.OUTPUT_FILE!r}")
