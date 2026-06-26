""" src/ml/dataset_storage.py — Store labeled trades as Apache Parquet. """

import pandas as pd
from pathlib import Path
import config


import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Union


def df_to_sample(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    candle_ts:int,
    side: str,
    setup_type: Any = None,
    result_r: Any = None,
) -> List[Dict[str, Any]]:
    """
    Converts an enriched DataFrame (from enrich_dataframe) into a list of dicts
    compatible with the sample format.

    Parameters
    ----------
    df : pd.DataFrame
        Enriched DataFrame (output of enrich_dataframe). Index should be datetime
        if you want candle_ts to be extracted automatically.
    symbol : str
        Symbol name (e.g., "BTCUSDT").
    timeframe : str
        Timeframe string (e.g., "1h", "4h").
    setup_type : any, optional
        Label for setup type. Can be a scalar (applied to all rows) or an
        iterable of length equal to len(df). Default None.
    result_r : any, optional
        Label for result (e.g., profit factor, win/loss). Same handling as setup_type.

    Returns
    -------
    List[Dict[str, Any]]
        A list of dictionaries, each representing one row with the sample schema:
        {
            "symbol": ...,
            "timeframe": ...,
            "candle_ts": ...,
            "setup_type": ...,
            "ema_alignment": ...,
            "rsi": ...,
            "stoch_rsi": ...,
            "macd_hist": ...,
            "volume_ratio": ...,
            "volume_trend": ...,
            "atr_pct": ...,
            "market_structure": ...,
            "distance_support": ...,
            "distance_resistance": ...,
            "result_r": ...
        }
    """
    sample = []
    


    # Mapping from sample key to DataFrame column name
    key_column_map = {
        # original entries
        "ema_alignment": "EMA alignment",
        "rsi": "RSI(14)",
        "stoch_rsi": "Stoch RSI",
        "macd_hist": "MACD histogram",
        "volume_ratio": "Volume ratio",
        "volume_trend": "Volume trend",
        "atr_pct": "ATR % price",
        "market_structure": "Market structure",
        "distance_support": "Distance to support %",
        "distance_resistance": "Distance to resistance %",
        "change_pct": "Change %",
        "position_in_period_range": "Position in period range",
        "ema9": "EMA9",
        "price_vs_ema9": "Price vs EMA9",
        "ema21": "EMA21",
        "price_vs_ema21": "Price vs EMA21",
        "ema50": "EMA50",
        "price_vs_ema50": "Price vs EMA50",
        "ema200": "EMA200",
        "price_vs_ema200": "Price vs EMA200",
        "ema50_vs_ema200": "EMA50 vs EMA200",
        "macd_line": "MACD line",
        "macd_signal": "MACD signal",
        "macd_cross": "MACD cross",
        "bb_width_pct": "BB width %",
        "bb_position": "BB position",
        "obv_trend": "OBV trend",
        "candle_type": "Candle type",
        "engulfing": "Engulfing",
        "last_3_candles": "Last 3 candles",
    }

    
    row = df.iloc[-1]


    sample = {
        "sample_id": f"{symbol}_{timeframe}_{candle_ts}_{setup_type}",
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_ts": candle_ts,
        "setup_type": setup_type,
        "side": side,
    }

    # Fill feature values – if column missing, use None
    for key, col in key_column_map.items():
        if col in df.columns:
            val = row[col]
            # Replace NaN with None for cleaner output
            if isinstance(val, float) and np.isnan(val):
                val = None
            sample[key] = val
        else:
            sample[key] = None

    if result_r is None:
        return
    sample["result_r"] = result_r
    

    return sample

def save_sample(sample_df: pd.DataFrame,symbol: str,timeframe: str,candle_ts:int,side: str,setup_type: str,result_r:float):
    DATASET_FILE = config.DATASET_DIR  + "/ml_dataset.csv"

    sample = df_to_sample(sample_df,symbol,timeframe,candle_ts,side,setup_type,result_r)
    
    df = pd.DataFrame([sample])

    if Path(DATASET_FILE).exists():
        df.to_csv(
            DATASET_FILE,
            mode="a",
            header=False,
            index=False,
            encoding="utf-8"
        )
    else:
        df.to_csv(
            DATASET_FILE,
            index=False,
            header=True,
            encoding="utf-8"
        )