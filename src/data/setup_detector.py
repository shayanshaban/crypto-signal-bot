"""
تشخیص ستاپ معاملاتی — قبل از هر چیز دیگه‌ای اجرا می‌شه.
اگه ستاپی نبود، AI صدا زده نمی‌شه.

supported setup :
  - ema_cross        
  - trend_pullback   
  - bb_squeeze       
  - breakout         
  - liquidity_sweep  
  - mean_reversion   
"""
from dataclasses import dataclass
import numpy as np
from src.data.baker import _ema, _rsi, _bollinger, _atr

@dataclass
class Setup:
    found:      bool
    setup_type: str | None
    direction:  str | None   # LONG / SHORT
    strength:   float        # 0-1


def detect(candles: list, timeframe: str = "15m") -> Setup:
    if not candles or len(candles) < 50:
        return Setup(False, None, None, 0)

    c = np.array([float(x[4]) for x in candles])
    h = np.array([float(x[2]) for x in candles])
    l = np.array([float(x[3]) for x in candles])
    v = np.array([float(x[5]) for x in candles])

    # check in the order
    result = (
        _check_ema_cross(c)         or
        _check_trend_pullback(c, v) or
        _check_bb_squeeze(c, v)     or
        _check_breakout(c, h, l, v) or
        _check_mean_reversion(c)
    )
    return result or Setup(False, None, None, 0)


def _check_ema_cross(c):
    e9  = _ema(c,      9)
    e21 = _ema(c,      21)
    e9p = _ema(c[:-1], 9)
    e21p= _ema(c[:-1], 21)
    if any(x is None for x in (e9, e21, e9p, e21p)):
        return None
    was_above = float(e9p[-1]) > float(e21p[-1])
    now_above = float(e9[-1])  > float(e21[-1])
    if was_above == now_above:
        return None
    direction = "LONG" if now_above else "SHORT"
    return Setup(True, "ema_cross", direction, 0.8)


def _check_trend_pullback(c, v):
    e9  = _ema(c, 9)
    e21 = _ema(c, 21)
    e50 = _ema(c, 50)
    if any(x is None for x in (e9, e21, e50)):
        return None

    bull_trend = float(e9[-1]) > float(e21[-1]) > float(e50[-1])
    bear_trend = float(e9[-1]) < float(e21[-1]) < float(e50[-1])

    last_c = float(c[-1])
    e21_val = float(e21[-1])
    near_ema = abs(last_c - e21_val) / e21_val < 0.003   # در ۰.۳٪ EMA21

    if bull_trend and near_ema:
        return Setup(True, "trend_pullback", "LONG", 0.75)
    if bear_trend and near_ema:
        return Setup(True, "trend_pullback", "SHORT", 0.75)
    return None


def _check_bb_squeeze(c, v):
    bb_u, bb_m, bb_l = _bollinger(c, 20, 2.0)
    if bb_u is None:
        return None
    width = (bb_u - bb_l) / bb_m * 100
    if width >= 1.5:   
        return None

    vol_avg = float(v[-21:-1].mean())
    vol_spike = vol_avg > 0 and float(v[-1]) >= vol_avg * 1.8

    if not vol_spike:
        return None

    last_c = float(c[-1])
    if last_c > bb_u:
        return Setup(True, "bb_squeeze", "LONG", 0.85)
    if last_c < bb_l:
        return Setup(True, "bb_squeeze", "SHORT", 0.85)
    return None


def _check_breakout(c, h, l, v):
    lookback = 20
    if len(c) < lookback + 5:
        return None

    recent_high = float(h[-lookback-1:-1].max())
    recent_low  = float(l[-lookback-1:-1].min())
    last_c = float(c[-1])

    vol_avg = float(v[-21:-1].mean())
    vol_spike = vol_avg > 0 and float(v[-1]) >= vol_avg * 1.5

    if last_c > recent_high and vol_spike:
        return Setup(True, "breakout", "LONG", 0.8)
    if last_c < recent_low and vol_spike:
        return Setup(True, "breakout", "SHORT", 0.8)
    return None


def _check_mean_reversion(c):
    from src.data.baker import _rsi
    rsi_now  = _rsi(c,      14)
    rsi_prev = _rsi(c[:-1], 14)
    if rsi_now is None or rsi_prev is None:
        return None

    if rsi_prev <= 25 and rsi_now > 25:
        return Setup(True, "mean_reversion", "LONG", 0.7)
    if rsi_prev >= 75 and rsi_now < 75:
        return Setup(True, "mean_reversion", "SHORT", 0.7)
    return None