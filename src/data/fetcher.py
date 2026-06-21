"""
src/data/fetcher.py — Market data retrieval from LBank and Wallex.

Public API:
  fetch_data()           — assemble the full multi-TF prompt file (LBank)
  fetch_wallex(symbol)   — fetch 100 × 60-min candles from Wallex
"""

import time
import json
from pathlib import Path

import requests

import config
from src.data import baker
from src.db            import manager as db

# ── LBank ────────────────────────────────────────────────────────────────────

def _get_candles(timeframe: str, tf_minutes: int, count: int) -> dict:
    """Return raw kline JSON from LBank."""
    to_time   = int(time.time())
    from_time = to_time - (count * tf_minutes * 60)
    params = {
        "symbol": config.SYMBOL_LBANK,
        "size":   count,
        "type":   timeframe,
        "time":   from_time,
    }
    r = requests.get(config.LBANK_KLINE_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _get_current_price() -> dict:
    """Return the latest ticker from LBank."""
    r = requests.get(
        config.LBANK_TICKER_URL,
        params={"symbol": config.SYMBOL_LBANK},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_data() -> None:
    """
    Pull multi-timeframe OHLCV from LBank, prepend the system prompt,
    and write the assembled file to config.OUTPUT_FILE.
    """
    Path(config.OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)

    with open(config.OUTPUT_FILE, "w", encoding="utf-8") as out:

        # System prompt
        with open(config.PROMPT_FILE, "r", encoding="utf-8") as pf:
            out.write(pf.read())

        # Header
        out.write(f"Symbol : {config.SYMBOL_LBANK}\n")
        out.write(
            "Data-Format : "
            "[[Timestamp, Open, High, Low, Close, Volume]]\n\n"
        )

        # Current price
        ticker = _get_current_price()
        current_price = float(ticker['data'][0]['price'])
        out.write(f"Current Price     : {ticker['data'][0]['price']}\n")
        out.write(f"Current Timestamp : {ticker['ts']}\n\n")

        # Candles
        for tf_key, tf_cfg in config.CANDLES.items():
            label = config.TIMEFRAME_LABELS[tf_key]
            data  = _get_candles(tf_key, tf_cfg["tf_minutes"], tf_cfg["count"])
            out.write(f"Time-Frame : {label}\n\n")
            raw_data = data["data"]
            if(tf_cfg["raw"] == False or tf_cfg["raw_and_bake"] == True):
                # Bake raw data
                data["data"] = baker.process_data(data["data"],current_price)
                for baked_data in data["data"]:
                    out.write(str(baked_data["label"])+" : "+str(baked_data["value"]) + "\n")
                out.write("\n")
            if(tf_cfg["raw"] == True or tf_cfg["raw_and_bake"] == True):
                for candle in raw_data:
                    out.write(str(candle) + "\n")
                out.write("\n")

def get_historical_data() -> None:
    """
    Get historical data for back testing .
    """      
    # Candles
    for tf_key, tf_cfg in config.BACK_TEST_CANDLES.items():
        data  = _get_candles(tf_key, tf_cfg["tf_minutes"], tf_cfg["count"])

        raw_data = data["data"]
        db.save_historical_candel(raw_data,tf_key)

def fetch_data_for_back_test(test_ts,thread_index) -> None:
    """
    Pull multi-timeframe OHLCV from LBank, prepend the system prompt,
    and write the assembled file to config.OUTPUT_FILE.
    """
    Path(config.BACK_TEST_OUTPUT_FILES[thread_index]).parent.mkdir(parents=True, exist_ok=True)

    with open(config.BACK_TEST_OUTPUT_FILES[thread_index], "w", encoding="utf-8") as out:

        # System prompt
        with open(config.PROMPT_FILE, "r", encoding="utf-8") as pf:
            out.write(pf.read())

        # Header
        out.write(f"Symbol : {config.SYMBOL_LBANK}\n")
        out.write(
            "Data-Format : "
            "[[Timestamp, Open, High, Low, Close, Volume]]\n\n"
        )

        # Current price
        ticker = db.get_current_price_from_db(test_ts)
        current_price = float(ticker['data'][0]['price'])
        out.write(f"Current Price     : {ticker['data'][0]['price']}\n")
        out.write(f"Current Timestamp : {ticker['ts']}\n\n")

        # Candles
        for tf_key, tf_cfg in config.CANDLES.items():
            label = config.TIMEFRAME_LABELS[tf_key]
            data  = db.get_candles_from_db(tf_key, tf_cfg["tf_minutes"], tf_cfg["count"],test_ts)
            out.write(f"Time-Frame : {label}\n\n")
            raw_data = data["data"]
            if(tf_cfg["raw"] == False or tf_cfg["raw_and_bake"] == True):
                # Bake raw data
                data["data"] = baker.process_data(data["data"],current_price)
                for baked_data in data["data"]:
                    out.write(str(baked_data["label"])+" : "+str(baked_data["value"]) + "\n")
                out.write("\n")
            if(tf_cfg["raw"] == True or tf_cfg["raw_and_bake"] == True):
                for candle in raw_data:
                    out.write(str(candle) + "\n")
                out.write("\n")

# ── Wallex ────────────────────────────────────────────────────────────────────

def fetch_wallex(symbol: str = config.SYMBOL_DISPLAY) -> list[dict]:
    """
    Fetch the last 100 × 60-min candles for *symbol* from Wallex.
    Returns a list of OHLCV dicts.
    """
    to_time   = int(time.time())
    from_time = to_time - (100 * 60 * 60)
    params = {
        "symbol":     symbol,
        "resolution": "60",
        "from":       from_time,
        "to":         to_time,
    }
    r = requests.get(
        config.WALLEX_KLINE_URL,
        params=params,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    raw = r.json()

    return [
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
