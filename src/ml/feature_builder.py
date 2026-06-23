"""
ساخت feature vector فشرده برای ذخیره در ml_dataset.
حدود ۱۵-۲۰ ویژگی که به AI و ML هر دو می‌رن.
"""
import json
import numpy as np
from datetime import datetime
from src.data.baker import (
    _ema, _rsi, _stoch_rsi, _macd, _atr, _bollinger,
    _market_structure, _obv_trend, _swing_points,
    _nearest_levels, _candle_type, _engulfing
)
from src.data.setup_detector import Setup


def build(candles: list, setup: Setup, current_price: float) -> dict:
    """
    Returns a flat dict of ~20 features suitable for:
      - LLM prompt (JSON format)
      - ML dataset storage
    """
    c = np.array([float(x[4]) for x in candles])
    h = np.array([float(x[2]) for x in candles])
    l = np.array([float(x[3]) for x in candles])
    o = np.array([float(x[1]) for x in candles])
    v = np.array([float(x[5]) for x in candles])

    last_c  = float(c[-1])
    vol_avg = float(v[-21:-1].mean()) if len(v) >= 21 else float(v.mean())
    atr     = _atr(h, l, c, 14) or 0
    rsi     = _rsi(c, 14)
    srsi    = _stoch_rsi(c)
    e21     = _ema(c, 21)
    e50     = _ema(c, 50)
    macd_v, macd_s, _ = _macd(c)
    bb_u, bb_m, bb_l  = _bollinger(c, 20, 2.0)

    e21_val = float(e21[-1]) if e21 is not None else None
    e50_val = float(e50[-1]) if e50 is not None else None
    bb_pos  = round((last_c - bb_l) / (bb_u - bb_l) * 100, 1) if bb_u and bb_u != bb_l else 50.0
    bb_width= round((bb_u - bb_l) / bb_m * 100, 2) if bb_u and bb_m else None

    sh, sl  = _swing_points(h, l, 3)
    levels  = _nearest_levels(sh + sl, current_price, 3)
    sup     = levels["nearest_supports"]
    res     = levels["nearest_resistances"]

    dist_support    = round((current_price - sup[0]) / current_price * 100, 2) if sup    else None
    dist_resistance = round((res[0] - current_price) / current_price * 100, 2) if res    else None

    # Higher Timeframe Bias — از market structure خود candle ها
    htf_bias = _market_structure(c)

    # زمان
    ts   = int(candles[-1][0])
    dt   = datetime.fromtimestamp(ts)

    return {
        "setup_type":           setup.setup_type,
        "market_structure":     _market_structure(c),
        "ema_alignment":        _ema_alignment(c),
        "price_vs_ema21":       round((last_c - e21_val) / e21_val * 100, 2) if e21_val else None,
        "price_vs_ema50":       round((last_c - e50_val) / e50_val * 100, 2) if e50_val else None,
        "rsi":                  rsi,
        "stoch_rsi":            srsi,
        "macd_position":        "above_signal" if (macd_v and macd_s and macd_v > macd_s) else "below_signal",
        "volume_ratio":         round(float(v[-1]) / vol_avg, 2) if vol_avg else None,
        "volume_trend":         _vol_trend(v),
        "obv_trend":            _obv_trend(c, v, 5),
        "atr_percent":          round(atr / last_c * 100, 2) if last_c else None,
        "bb_position":          bb_pos,
        "bb_width":             bb_width,
        "bb_squeeze":           bb_width < 1.5 if bb_width else False,
        "distance_support":     dist_support,
        "distance_resistance":  dist_resistance,
        "nearest_supports":     sup,
        "nearest_resistances":  res,
        "last_candle":          _candle_type(float(o[-1]), float(h[-1]), float(l[-1]), last_c),
        "bias":                 _bias(rsi, macd_v, c, e21_val),
        "hour_of_day":          dt.hour,
        "day_of_week":          dt.weekday(),
        "higher_tf_bias":       htf_bias,
    }


def to_json(features: dict) -> str:
    return json.dumps(features, ensure_ascii=False, indent=2)


def _ema_alignment(c):
    e9  = _ema(c, 9)
    e21 = _ema(c, 21)
    e50 = _ema(c, 50)
    if any(x is None for x in (e9, e21, e50)):
        return "unknown"
    if float(e9[-1]) > float(e21[-1]) > float(e50[-1]):
        return "bull"
    if float(e9[-1]) < float(e21[-1]) < float(e50[-1]):
        return "bear"
    return "mixed"


def _vol_trend(v):
    if len(v) < 10:
        return "unknown"
    if v[-5:].mean() > v[-10:-5].mean() * 1.1:
        return "increasing"
    if v[-5:].mean() < v[-10:-5].mean() * 0.9:
        return "decreasing"
    return "flat"


def _bias(rsi, macd_v, c, e21_val):
    bull = bear = 0
    if rsi:
        if rsi > 55: bull += 1
        elif rsi < 45: bear += 1
    if macd_v:
        if macd_v > 0: bull += 1
        else: bear += 1
    if e21_val and len(c) > 0:
        if float(c[-1]) > e21_val: bull += 1
        else: bear += 1
    return "bullish" if bull > bear else "bearish" if bear > bull else "neutral"