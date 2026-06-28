"""
src/data/baker.py — Compress raw OHLCV candles into labeled indicators.

Public API:
  process_data(candles)  — list[[ts,o,h,l,c,v]] → list[{"label", "value"}]
"""

from __future__ import annotations
import numpy as np
from typing import Any
import pandas as pd
from tqdm import tqdm

# ── indicator helpers ─────────────────────────────────────────────────────────

def _ema(arr: np.ndarray, period: int) -> np.ndarray | None:
    """Exponential Moving Average (k = 2 / (n+1))."""
    if len(arr) < period:
        return None
    k   = 2.0 / (period + 1)
    out = np.empty(len(arr) - period + 1)
    out[0] = arr[:period].mean()
    for i in range(1, len(out)):
        out[i] = arr[period - 1 + i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(closes: np.ndarray, period: int = 14) -> float | None:
    """RSI using Wilder's smoothing."""
    if len(closes) < period + 1:
        return None
    d     = np.diff(closes)
    gains = np.where(d > 0,  d, 0.0)
    loses = np.where(d < 0, -d, 0.0)

    ag = gains[:period].mean()
    al = loses[:period].mean()
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + loses[i]) / period

    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag / al), 2)


def _stoch_rsi(closes: np.ndarray, rsi_p: int = 14, stoch_p: int = 14) -> float | None:
    """Stochastic RSI (0–100)."""
    if len(closes) < rsi_p + stoch_p + 1:
        return None
    series = np.array([
        _rsi(closes[:len(closes) - stoch_p + i + 1], rsi_p)
        for i in range(stoch_p)
    ], dtype=float)
    if np.any(np.isnan(series)):
        return None
    lo, hi = series.min(), series.max()
    if hi == lo:
        return 50.0
    return round(float((series[-1] - lo) / (hi - lo) * 100), 2)


def _macd(closes: np.ndarray, fast=12, slow=26, signal=9):
    """(macd_val, signal_val, histogram) for the last bar."""
    if len(closes) < slow + signal:
        return None, None, None
    ef = _ema(closes, fast)
    es = _ema(closes, slow)
    if ef is None or es is None:
        return None, None, None
    macd_line = ef[slow - fast:] - es       # aligned, same length as es
    sig_line  = _ema(macd_line, signal)
    if sig_line is None:
        return None, None, None
    return (
        round(float(macd_line[-1]), 8),
        round(float(sig_line[-1]),  8),
        round(float(macd_line[-1] - sig_line[-1]), 8),
    )


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float | None:
    """Average True Range via Wilder's smoothing."""
    if len(c) < period + 1:
        return None
    tr = np.maximum(h[1:] - l[1:],
         np.maximum(np.abs(h[1:] - c[:-1]),
                    np.abs(l[1:] - c[:-1])))
    atr = tr[:period].mean()
    for t in tr[period:]:
        atr = (atr * (period - 1) + t) / period
    return round(float(atr), 8)


def _bollinger(closes: np.ndarray, period: int = 20, mult: float = 2.0):
    """Bollinger Bands for last bar: (upper, mid, lower)."""
    if len(closes) < period:
        return None, None, None
    w   = closes[-period:]
    mid = float(w.mean())
    std = float(w.std())
    return round(mid + mult * std, 8), round(mid, 8), round(mid - mult * std, 8)


def _swing_points(h: np.ndarray, l: np.ndarray, lookback: int = 3):
    """Last 3 swing highs and lows."""
    sh, sl = [], []
    for i in range(lookback, len(h) - lookback):
        if h[i] == h[i - lookback: i + lookback + 1].max():
            sh.append(round(float(h[i]), 8))
        if l[i] == l[i - lookback: i + lookback + 1].min():
            sl.append(round(float(l[i]), 8))
    return sh[-3:], sl[-3:]


def _market_structure(closes: np.ndarray) -> str:
    """HH/HL, LH/LL, ranging, expanding, or contracting."""
    if len(closes) < 20:
        return "unknown"
    q    = len(closes) // 4
    segs = [closes[i * q: (i + 1) * q] for i in range(4)]
    ph   = [s.max() for s in segs]
    pl   = [s.min() for s in segs]
    hh   = ph[-1] > ph[-2] > ph[-3]
    hl   = pl[-1] > pl[-2] > pl[-3]
    lh   = ph[-1] < ph[-2] < ph[-3]
    ll   = pl[-1] < pl[-2] < pl[-3]
    if hh and hl: return "HH_HL (uptrend)"
    if lh and ll: return "LH_LL (downtrend)"
    if hh and ll: return "expanding"
    if lh and hl: return "contracting"
    return "ranging"


def _candle_type(o: float, h: float, l: float, c: float) -> str:
    rng = h - l
    if rng == 0:
        return "doji"
    body       = abs(c - o)
    body_r     = body / rng
    upper_wick = (h - max(o, c)) / rng
    lower_wick = (min(o, c) - l) / rng
    bull       = c >= o

    if body_r < 0.1:
        return "doji"
    if lower_wick > 0.55 and body_r < 0.35:
        return "hammer" if bull else "hanging_man"
    if upper_wick > 0.55 and body_r < 0.35:
        return "inverted_hammer" if bull else "shooting_star"
    if upper_wick > 0.45 and lower_wick > 0.45 and body_r < 0.1:
        return "spinning_top"
    if body_r > 0.7:
        return "marubozu_bull" if bull else "marubozu_bear"
    return "bull" if bull else "bear"


def _engulfing(po: float, pc: float, co: float, cc: float) -> str | None:
    if not pc or not po:
        return None
    prev_bull = pc > po
    curr_bull = cc > co
    if not prev_bull and curr_bull and co <= pc and cc >= po:
        return "bullish_engulfing"
    if prev_bull and not curr_bull and co >= pc and cc <= po:
        return "bearish_engulfing"
    return None


def _obv_trend(c: np.ndarray, v: np.ndarray, lookback: int = 5) -> str:
    """Rising or falling OBV over last `lookback` bars."""
    if len(c) < lookback + 1:
        return "unknown"
    signs = np.sign(np.diff(c[-lookback - 1:]))
    obv_delta = float((signs * v[-lookback:]).sum())
    return "rising" if obv_delta > 0 else "falling" if obv_delta < 0 else "flat"


def _nearest_levels(levels: list[float], current_price: float, n: int = 3) -> dict:
    """Sort swing levels and split into nearest supports/resistances vs current price."""
    sorted_levels = sorted(set(levels))
    below = [lv for lv in sorted_levels if lv < current_price]
    above = [lv for lv in sorted_levels if lv > current_price]
    return {
        "nearest_supports":    below[-n:][::-1],   # closest first
        "nearest_resistances": above[:n],
    }

def _ema_series(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    ema = np.full(n, np.nan, dtype=float)
    if n < period:
        return ema
    k = 2.0 / (period + 1)
    ema[period - 1] = close[:period].mean()          # مقدار اولیه SMA
    for i in range(period, n):
        ema[i] = close[i] * k + ema[i - 1] * (1 - k)
    return ema

# ── RSI: آرایه‌ی کامل (مقداردهی از اندیس 14 به بعد) ──────
def _rsi_series(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    rsi = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return rsi
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    # اولین مقدار میانگین: میانگین ساده‌ی 14 کندل اول (دلتاها)
    avg_gain[period] = gain[1:period+1].mean()      # gain[1] تا gain[period]
    avg_loss[period] = loss[1:period+1].mean()
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + loss[i]) / period
    rs = avg_gain / avg_loss
    with np.errstate(divide='ignore', invalid='ignore'):
        rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

# ── Stochastic RSI: آرایه‌ی کامل ──────────────────────────
def _stoch_rsi_series(close: np.ndarray, rsi_period: int = 14, stoch_period: int = 14) -> np.ndarray:
    n = len(close)
    stoch = np.full(n, np.nan, dtype=float)
    if n < rsi_period + stoch_period + 1:
        return stoch
    rsi_vals = _rsi_series(close, rsi_period)
    s = pd.Series(rsi_vals)
    min_rsi = s.rolling(stoch_period).min().to_numpy()
    max_rsi = s.rolling(stoch_period).max().to_numpy()
    denom = max_rsi - min_rsi
    denom[denom == 0] = np.nan
    stoch = (rsi_vals - min_rsi) / denom * 100.0
    # در حلقه‌ی قدیمی اگر یکی از RSIها NaN بود None برمی‌گشت → ما NaN داریم
    return stoch

# ── MACD: سه آرایه macd_line, signal, histogram (طول N) ─
def _macd_series(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    n = len(close)
    macd_line = np.full(n, np.nan)
    signal_line = np.full(n, np.nan)
    hist = np.full(n, np.nan)
    if n < slow + signal:
        return macd_line, signal_line, hist
    ema_fast = _ema_series(close, fast)
    ema_slow = _ema_series(close, slow)
    raw_macd = ema_fast - ema_slow
    ema_signal = _ema_series(raw_macd, signal)
    # در حلقه‌ی اصلی از i=35 شروع می‌کرد (اندیس 34 اولین مقدار)
    start = slow + signal - 2  # 26+9-2 = 33
    first_valid = max(start, 0)
    if n > first_valid:
        macd_line[first_valid:] = raw_macd[first_valid:]
        signal_line[first_valid:] = ema_signal[first_valid:]
        hist[first_valid:] = macd_line[first_valid:] - signal_line[first_valid:]
    return macd_line, signal_line, hist

# ── ATR: آرایه‌ی کامل (وایلدر) ─────────────────────────────
def _atr_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close),
                               np.abs(low - prev_close)))
    atr[period] = tr[1:period+1].mean()               # tr[1] تا tr[period] (14 مقدار)
    for i in range(period + 1, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr

# ── بولینگر: سه آرایه upper, mid, lower (طول N) ──────────
def _bollinger_series(close: np.ndarray, period: int = 20, nbdev: float = 2.0):
    n = len(close)
    mid = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    if n < period:
        return upper, mid, lower
    s = pd.Series(close)
    mid = s.rolling(period).mean().to_numpy()
    # ddof=0 برای تطابق با std() پیش‌فرض NumPy (تقسیم بر N)
    std = s.rolling(period).std(ddof=0).to_numpy()
    upper = mid + nbdev * std
    lower = mid - nbdev * std
    return upper, mid, lower

# ── OBV و روند آن ────────────────────────────────────────
def _obv_series(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    n = len(close)
    if n == 0:
        return np.array([])
    direction = np.sign(np.diff(close, prepend=close[0]))
    obv = np.cumsum(np.where(direction == 1, volume,
                             np.where(direction == -1, -volume, 0.0)))
    return obv

def _obv_trend_series(close: np.ndarray, volume: np.ndarray, lookback: int = 5) -> np.ndarray:
    n = len(close)
    trend = np.full(n, np.nan)
    if n < lookback + 1:
        return trend
    obv = _obv_series(close, volume)
    s = pd.Series(obv)
    ma = s.rolling(lookback).mean().to_numpy()
    for i in range(lookback, n):
        if not np.isnan(ma[i]):
            if obv[i] > ma[i]:
                trend[i] = 1
            elif obv[i] < ma[i]:
                trend[i] = -1
            else:
                trend[i] = 0
    return trend



def find_swing_series(
    high: np.ndarray,
    low: np.ndarray,
    lookback: int = 3,
):
    """
    Detect swing highs/lows once.

    Returns
    -------
    swing_highs : np.ndarray
        NaN except at swing highs.

    swing_lows : np.ndarray
        NaN except at swing lows.
    """

    n = len(high)

    swing_highs = np.full(n, np.nan)
    swing_lows = np.full(n, np.nan)

    for i in range(lookback, n - lookback):

        if high[i] >= np.max(high[i-lookback:i+lookback+1]):
            swing_highs[i] = high[i]

        if low[i] <= np.min(low[i-lookback:i+lookback+1]):
            swing_lows[i] = low[i]

    return swing_highs, swing_lows
def last_swing_series(
    swing_highs: np.ndarray,
    swing_lows: np.ndarray,
):
    """
    For every candle return the latest swing high and swing low.
    """

    n = len(swing_highs)

    last_high = np.full(n, np.nan)
    last_low = np.full(n, np.nan)

    cur_high = np.nan
    cur_low = np.nan

    for i in range(n):

        if not np.isnan(swing_highs[i]):
            cur_high = swing_highs[i]

        if not np.isnan(swing_lows[i]):
            cur_low = swing_lows[i]

        last_high[i] = cur_high
        last_low[i] = cur_low

    return last_high, last_low
# ── public API ────────────────────────────────────────────────────────────────
def should_ask_ai(candles: list, current_price: float | None = None) -> bool:
    """
    Returns True only when at least one high-probability setup is detected,
    so the AI is called only on meaningful candles instead of every single one.

    Triggers (any one is enough):
      1. MACD bullish or bearish cross
      2. RSI crossed into/out of overbought or oversold zone
      3. Price touched or broke Bollinger Band + volume spike
      4. Bullish or bearish engulfing with above-average volume
      5. EMA9 / EMA21 cross
    """
    if not candles or len(candles) < 30:
        return False

    o = np.array([float(c[1]) for c in candles])
    h = np.array([float(c[2]) for c in candles])
    l = np.array([float(c[3]) for c in candles])
    c = np.array([float(c[4]) for c in candles])
    v = np.array([float(c[5]) for c in candles])

    # ── 1) MACD cross ─────────────────────────────────────────────────────────
    macd_v,  _, _ = _macd(c)
    macd_pv, _, _ = _macd(c[:-1])
    if macd_v is not None and macd_pv is not None:
        macd_s  = _ema(_ema(c,      12)[26-12:] - _ema(c,      26), 9)
        macd_ps = _ema(_ema(c[:-1], 12)[26-12:] - _ema(c[:-1], 26), 9)
        if macd_s is not None and macd_ps is not None:
            prev_above = macd_pv > float(macd_ps[-1])
            curr_above = macd_v  > float(macd_s[-1])
            if prev_above != curr_above:   # cross happened this candle
                return True

    # ── 2) RSI zone cross ─────────────────────────────────────────────────────
    rsi_now  = _rsi(c,      14)
    rsi_prev = _rsi(c[:-1], 14)
    if rsi_now is not None and rsi_prev is not None:
        for level in (30, 70):
            crossed = (rsi_prev < level <= rsi_now) or (rsi_prev > level >= rsi_now)
            if crossed:
                return True

    # ── 3) BB touch + volume spike ────────────────────────────────────────────
    bb_u, bb_m, bb_l = _bollinger(c, 20, 2.0)
    if bb_u is not None:
        vol_avg = float(v[-21:-1].mean()) if len(v) >= 21 else float(v[:-1].mean())
        vol_spike = vol_avg > 0 and float(v[-1]) >= vol_avg * 1.5
        last_c = float(c[-1])
        if vol_spike and (last_c >= bb_u or last_c <= bb_l):
            return True

    # ── 4) Engulfing + above-average volume ───────────────────────────────────
    eng = _engulfing(float(o[-2]), float(c[-2]), float(o[-1]), float(c[-1]))
    if eng is not None:
        vol_avg = float(v[-21:-1].mean()) if len(v) >= 21 else float(v[:-1].mean())
        if vol_avg > 0 and float(v[-1]) >= vol_avg * 1.2:
            return True

    # ── 5) EMA9 / EMA21 cross ─────────────────────────────────────────────────
    e9_now  = _ema(c,      9)
    e21_now = _ema(c,      21)
    e9_prev = _ema(c[:-1], 9)
    e21_prev= _ema(c[:-1], 21)
    if all(x is not None for x in (e9_now, e21_now, e9_prev, e21_prev)):
        prev_above = float(e9_prev[-1]) > float(e21_prev[-1])
        curr_above = float(e9_now[-1])  > float(e21_now[-1])
        if prev_above != curr_above:
            return True

    return False

def enrich_dataframe(df: pd.DataFrame, show_progress: bool = False) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    o = df["Open"].to_numpy(dtype=float)
    v = df["Volume"].to_numpy(dtype=float)
    N = len(c)

    if show_progress:
        pbar = tqdm(total=14, desc="Enriching OHLCV data", unit="step")
    else:
        pbar = None

    # ── قیمت‌ها و Change % ────────────────────────────────
    df["Close"] = c
    df["Open"]  = o
    df["High"]  = h
    df["Low"]   = l
    change = np.full(N, np.nan)
    if N >= 2:
        change[1:] = np.diff(c) / c[:-1] * 100
    df["Change %"] = change

    # ── محدوده‌ی دوره (O(N)) ─────────────────────────────
    period_high = np.maximum.accumulate(h)
    period_low  = np.minimum.accumulate(l)
    df["Period high"] = period_high
    df["Period low"]  = period_low
    pos_in_range = (c - period_low) / (period_high - period_low) * 100
    pos_in_range[np.isnan(pos_in_range)] = 50.0
    df["Position in period range"] = pos_in_range
    if pbar: pbar.update(1)

    # ── EMA ها ───────────────────────────────────────────
    for period in (9, 21, 50, 200):
        e = _ema_series(c, period)
        df[f"EMA{period}"] = e
        with np.errstate(divide='ignore', invalid='ignore'):
            diff = (c - e) / e * 100
            diff[np.isinf(diff)] = np.nan
        df[f"Price vs EMA{period}"] = diff
    e9, e21, e50, e200 = df["EMA9"].values, df["EMA21"].values, df["EMA50"].values, df["EMA200"].values
    if pbar: pbar.update(1)

    # ── EMA alignment / cross ────────────────────────────
    align = np.zeros(N)
    align[(e9 > e21) & (e21 > e50)] = 1
    align[(e9 < e21) & (e21 < e50)] = -1
    align[np.isnan(e9) | np.isnan(e21) | np.isnan(e50)] = np.nan
    df["EMA alignment"] = align

    cross_zone = np.zeros(N)
    cross_zone[e50 > e200] = 1
    cross_zone[e50 < e200] = -1
    cross_zone[np.isnan(e50) | np.isnan(e200)] = np.nan
    df["EMA50 vs EMA200"] = cross_zone
    if pbar: pbar.update(1)

    df["EMA9 slope"] = (e9 - np.roll(e9, 5)) / np.roll(e9, 5) * 100
    df["EMA21 slope"] = (e21 - np.roll(e21, 5)) / np.roll(e21, 5) * 100
    df["EMA50 slope"] = (e50 - np.roll(e50, 5)) / np.roll(e50, 5) * 100
    df["EMA200 slope"] = (e200 - np.roll(e200, 5)) / np.roll(e200, 5) * 100 
    # ── RSI ──────────────────────────────────────────────
    rsi_arr = _rsi_series(c, 14)
    df["RSI(14)"] = rsi_arr
    rsi_zone = np.full(N, np.nan, dtype=object)
    rsi_zone[rsi_arr >= 70] = "overbought"
    rsi_zone[rsi_arr <= 30] = "oversold"
    rsi_zone[(rsi_arr > 50) & (rsi_arr < 70)] = "bullish zone"
    rsi_zone[(rsi_arr > 30) & (rsi_arr < 50)] = "bearish zone"
    rsi_zone[(rsi_arr >= 50) & (rsi_arr <= 55)] = "neutral"
    rsi_zone[(rsi_arr >= 45) & (rsi_arr < 50)] = "neutral"
    df["RSI zone"] = rsi_zone
    if pbar: pbar.update(1)

    rsi_slope = rsi_arr - np.roll(rsi_arr,5)
    df["RSI slope"] = rsi_slope
    # ── Stoch RSI ────────────────────────────────────────
    stoch_arr = _stoch_rsi_series(c, 14, 14)
    df["Stoch RSI"] = stoch_arr
    stoch_zone = np.full(N, np.nan, dtype=object)
    stoch_zone[stoch_arr >= 80] = "overbought"
    stoch_zone[stoch_arr <= 20] = "oversold"
    stoch_zone[(stoch_arr > 20) & (stoch_arr < 80)] = "neutral"
    df["Stoch RSI zone"] = stoch_zone
    if pbar: pbar.update(1)

    df["Stoch RSI slope"] = stoch_arr - np.roll(stoch_arr,5)
    # ── MACD ─────────────────────────────────────────────
    macd_line, macd_sig, macd_hist = _macd_series(c)
    df["MACD line"]      = macd_line
    df["MACD signal"]    = macd_sig
    df["MACD histogram"] = macd_hist
    macd_pos = np.full(N, np.nan, dtype=object)
    macd_pos[macd_line > macd_sig] = "above signal"
    macd_pos[macd_line < macd_sig] = "below signal"
    df["MACD position"] = macd_pos
    if pbar: pbar.update(1)

    # ── MACD cross ───────────────────────────────────────
    macd_cross = np.zeros(N)
    for i in range(1, N):
        if np.isnan(macd_line[i]) or np.isnan(macd_sig[i]) or np.isnan(macd_line[i-1]) or np.isnan(macd_sig[i-1]):
            continue
        prev_above = macd_line[i-1] > macd_sig[i-1]
        curr_above = macd_line[i]   > macd_sig[i]
        if not prev_above and curr_above:
            macd_cross[i] = 1
        elif prev_above and not curr_above:
            macd_cross[i] = -1
    df["MACD cross"] = macd_cross
    if pbar: pbar.update(1)

    # ── Bollinger Bands ──────────────────────────────────
    bb_u, bb_m, bb_l = _bollinger_series(c, 20, 2.0)
    df["BB upper"] = bb_u
    df["BB mid"]   = bb_m
    df["BB lower"] = bb_l
    bb_width = np.where(bb_m != 0, (bb_u - bb_l) / bb_m * 100, np.nan)
    df["BB width %"] = bb_width
    bb_pos = np.where(bb_u != bb_l, (c - bb_l) / (bb_u - bb_l) * 100, 50.0)
    df["BB position"] = bb_pos
    bb_signal = np.full(N, np.nan, dtype=object)
    bb_signal[c > bb_u] = "above upper"
    bb_signal[c < bb_l] = "below lower"
    bb_signal[(c >= bb_l) & (c <= bb_u)] = "inside bands"
    df["BB signal"] = bb_signal
    df["BB squeeze"] = np.where(bb_width < 2.0, "yes", "no")
    if pbar: pbar.update(1)

    # ── ATR ──────────────────────────────────────────────
    atr_abs = _atr_series(h, l, c, 14)
    df["ATR(14)"] = atr_abs
    atr_pct = np.where(c != 0, atr_abs / c, np.nan)
    df["ATR % price"] = atr_pct
    if pbar: pbar.update(1)

    # ── Volume ───────────────────────────────────────────
    df["Volume"] = v
    vol_avg = pd.Series(v).rolling(20, min_periods=1).mean().to_numpy().copy()
    vol_avg[:19] = np.nan
    df["Volume avg(20)"] = vol_avg
    with np.errstate(divide='ignore', invalid='ignore'):
        vol_ratio = v / vol_avg
        vol_ratio[np.isinf(vol_ratio)] = np.nan
    df["Volume ratio"] = vol_ratio
    vol_signal = np.full(N, np.nan, dtype=object)
    vol_signal[vol_ratio >= 2.0] = "very high"
    vol_signal[(vol_ratio >= 1.3) & (vol_ratio < 2.0)] = "above average"
    vol_signal[vol_ratio <= 0.5] = "very low"
    vol_signal[(vol_ratio > 0.5) & (vol_ratio < 1.3)] = "normal"
    df["Volume signal"] = vol_signal
    if pbar: pbar.update(1)

    # ── Volume trend (برداری) ────────────────────────────
    vol_trend = np.zeros(N)
    if N >= 10:
        cur5 = pd.Series(v).rolling(5).mean().to_numpy()
        prev5 = pd.Series(v).shift(5).rolling(5).mean().to_numpy()
        vol_trend = np.where(cur5 > prev5 * 1.1, 1,
                             np.where(cur5 < prev5 * 0.9, -1, 0))
        vol_trend[:9] = 0
    df["Volume trend"] = vol_trend

    # ── OBV trend (برداری) ───────────────────────────────
    df["OBV trend"] = _obv_trend_series(c, v, lookback=5)
    if pbar: pbar.update(1)

    # ── Market structure (بدون تغییر) ────────────────────
    df["Market structure"] = _market_structure(c)
    if pbar: pbar.update(1)

    # ── Candle type, Engulfing, Last 3 candles ───────────
    ct = np.array([_candle_type(o[i], h[i], l[i], c[i]) for i in range(N)], dtype=object)
    df["Candle type"] = ct

    engulf = np.full(N, None, dtype=object)
    for i in range(1, N):
        engulf[i] = _engulfing(o[i-1], c[i-1], o[i], c[i])
    df["Engulfing"] = engulf

    last3 = np.full(N, None, dtype=object)
    for i in range(2, N):
        parts = ["bull" if c[j] > o[j] else "bear" for j in range(i-2, i+1)]
        last3[i] = " → ".join(parts)
    df["Last 3 candles"] = last3
    if pbar: pbar.update(1)

    df["Return 1"] = pd.Series(c).pct_change(1)*100
    df["Return 3"] = pd.Series(c).pct_change(3)*100
    df["Return 5"] = pd.Series(c).pct_change(5)*100
    df["Return 10"] = pd.Series(c).pct_change(10)*100
    df["Return 20"] = pd.Series(c).pct_change(20)*100

    df["Volatility 10"] = pd.Series(c).pct_change().rolling(10).std()

    df["Volatility 20"] = pd.Series(c).pct_change().rolling(20).std()

    df["Highest 20"] = pd.Series(h).rolling(20).max()

    df["Lowest 20"] = pd.Series(l).rolling(20).min()

    df["Distance Highest20"] = (df["Highest 20"]-c)/c*100

    df["Distance Lowest20"] = (c-df["Lowest 20"])/c*100

    body=np.abs(c-o)

    df["Body %"]=body/c*100

    upper=h-np.maximum(o,c)

    df["Upper wick %"]=upper/c*100

    lower=np.minimum(o,c)-l

    df["Lower wick %"]=lower/c*100

    df["Prev High Dist"]=(c-pd.Series(h).shift(1))/c*100

    df["Prev Low Dist"]=(c-pd.Series(l).shift(1))/c*100

    bull=(c>o).astype(int)

    df["Bull Ratio 10"]=pd.Series(bull).rolling(10).mean()

    df["Avg Body10"]=pd.Series(body).rolling(10).mean()

    df["Close Position"]=(c-l)/(h-l)*100

    dt = pd.to_datetime(df["Timestamp"], unit="s")

    df["Hour"] = dt.dt.hour.astype(np.int8)

    df["Day of Week"] = dt.dt.dayofweek.astype(np.int8)

    session = np.full(N, "Other", dtype=object)

    session[(df["Hour"] >= 0) & (df["Hour"] < 8)] = "Asia"

    session[(df["Hour"] >= 8) & (df["Hour"] < 16)] = "London"

    session[(df["Hour"] >= 13) & (df["Hour"] < 21)] = "New York"

    df["Session"] = session

    trend_age = np.zeros(N, dtype=np.int32)

    for i in range(1, N):
        if align[i] == align[i-1]:
            trend_age[i] = trend_age[i-1] + 1
        else:
            trend_age[i] = 0

    df["Trend age"] = trend_age

    bars_since_cross = np.zeros(N, dtype=np.int32)

    counter = 100000

    for i in range(1, N):

        crossed = (
            (e9[i-1] <= e21[i-1] and e9[i] > e21[i]) or
            (e9[i-1] >= e21[i-1] and e9[i] < e21[i])
        )

        if crossed:
            counter = 0
        else:
            counter += 1

        bars_since_cross[i] = counter

    df["Bars Since EMA Cross"] = bars_since_cross

    df["EMA9 vs EMA21"] = np.where(
        e21 != 0,
        (e9 - e21) / e21 * 100,
        np.nan
    )
    

    # ── Distance to support / resistance (همان حلقه‌ی قبلی) ─
    swing_highs, swing_lows = find_swing_series(
    h,
    l,
    lookback=3,
    )

    last_high, last_low = last_swing_series(
        swing_highs,
        swing_lows,
    )
    df["Distance Last Swing High"] = (
    (last_high - c) / c * 100
    )

    df["Distance Last Swing Low"] = (
        (c - last_low) / c * 100
    )
    df["Distance to support %"] = (
    (c - last_low) / c * 100
    )

    df["Distance to resistance %"] = (
        (last_high - c) / c * 100
    )
    if pbar:
        pbar.update(1)
        pbar.close()

    return df

def calculate_reward_r(
    side: str,
    entry_price: float,
    exit_price: float,
    stop_loss: float,
) -> float:
    """
    Calculate trade result in R units.

    Returns:
        +2.0 => profit equal to 2R
        -1.0 => stop loss hit
        +0.5 => half R profit
        -0.3 => 0.3R loss
    """

    side = side.upper()

    if side == "LONG":
        risk = entry_price - stop_loss
        profit = exit_price - entry_price

    elif side == "SHORT":
        risk = stop_loss - entry_price
        profit = entry_price - exit_price

    else:
        raise ValueError("side must be LONG or SHORT")

    if risk <= 0:
        raise ValueError("Invalid stop loss")

    return round(profit / risk, 4)