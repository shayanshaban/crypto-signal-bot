"""
src/data/baker.py — Compress raw OHLCV candles into labeled indicators.

Public API:
  process_data(candles)  — list[[ts,o,h,l,c,v]] → list[{"label", "value"}]
"""

from __future__ import annotations
import numpy as np
from typing import Any
import pandas as pd


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

def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert raw OHLCV DataFrame into a fully featured DataFrame.
    Each row gets all indicators that process_data would produce for that
    candle, as individual columns.
    """
    df = df.copy()
    c = df["Close"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    o = df["Open"].to_numpy(dtype=float)
    v = df["Volume"].to_numpy(dtype=float)
    N = len(c)

    # ── قیمت‌های اولیه ───────────────────────────────────────
    df["Close"] = c
    df["Open"]  = o
    df["High"]  = h
    df["Low"]   = l
    df["Change %"] = np.full(N, np.nan)
    if N >= 2:
        df.loc[df.index[1:], "Change %"] = (c[1:] - c[:-1]) / c[:-1] * 100

    # ── محدوده‌ی دوره ────────────────────────────────────────
    period_high = np.array([h[:i+1].max() for i in range(N)])
    period_low  = np.array([l[:i+1].min() for i in range(N)])
    df["Period high"] = period_high
    df["Period low"]  = period_low
    pos_in_range = (c - period_low) / (period_high - period_low) * 100
    pos_in_range[np.isnan(pos_in_range)] = 50.0
    df["Position in period range"] = pos_in_range

    # ── EMA ───────────────────────────────────────────────────
    for period in (9, 21, 50, 200):
        e = _ema(c, period)
        col = f"EMA{period}"
        out = np.full(N, np.nan)
        if e is not None:
            out[N - len(e):] = e
            df[col] = out
            with np.errstate(divide='ignore', invalid='ignore'):
                diff = (c - out) / out * 100
                diff[np.isinf(diff)] = np.nan
            df[f"Price vs EMA{period}"] = diff
        else:
            df[col] = np.nan
            df[f"Price vs EMA{period}"] = np.nan

    e9 = df["EMA9"].values if "EMA9" in df.columns else np.full(N, np.nan)
    e21 = df["EMA21"].values if "EMA21" in df.columns else np.full(N, np.nan)
    e50 = df["EMA50"].values if "EMA50" in df.columns else np.full(N, np.nan)
    e200 = df["EMA200"].values if "EMA200" in df.columns else np.full(N, np.nan)

    # ── EMA alignment (عددی) ─────────────────────────────────
    align = np.zeros(N)
    mask_bull = (e9 > e21) & (e21 > e50)
    mask_bear = (e9 < e21) & (e21 < e50)
    align[mask_bull] = 1
    align[mask_bear] = -1
    align[np.isnan(e9) | np.isnan(e21) | np.isnan(e50)] = np.nan
    df["EMA alignment"] = align

    # ── EMA50 vs EMA200 (عددی) ────────────────────────────────
    cross_zone = np.zeros(N)
    cross_zone[e50 > e200] = 1
    cross_zone[e50 < e200] = -1
    cross_zone[np.isnan(e50) | np.isnan(e200)] = np.nan
    df["EMA50 vs EMA200"] = cross_zone

    # ── RSI ───────────────────────────────────────────────────
    rsi_arr = np.full(N, np.nan)
    for i in range(15, N+1):
        val = _rsi(c[:i], 14)
        if val is not None:
            rsi_arr[i-1] = val
    df["RSI(14)"] = rsi_arr
    rsi_zone = np.full(N, np.nan, dtype=object)
    rsi_zone[rsi_arr >= 70] = "overbought"
    rsi_zone[rsi_arr <= 30] = "oversold"
    rsi_zone[(rsi_arr > 50) & (rsi_arr < 70)] = "bullish zone"
    rsi_zone[(rsi_arr > 30) & (rsi_arr < 50)] = "bearish zone"
    rsi_zone[(rsi_arr >= 50) & (rsi_arr <= 55)] = "neutral"  # for completeness
    rsi_zone[(rsi_arr >= 45) & (rsi_arr < 50)] = "neutral"
    df["RSI zone"] = rsi_zone

    # ── Stoch RSI ─────────────────────────────────────────────
    stoch_arr = np.full(N, np.nan)
    for i in range(29, N+1):
        val = _stoch_rsi(c[:i], 14, 14)
        if val is not None:
            stoch_arr[i-1] = val
    df["Stoch RSI"] = stoch_arr
    stoch_zone = np.full(N, np.nan, dtype=object)
    stoch_zone[stoch_arr >= 80] = "overbought"
    stoch_zone[stoch_arr <= 20] = "oversold"
    stoch_zone[(stoch_arr > 20) & (stoch_arr < 80)] = "neutral"
    df["Stoch RSI zone"] = stoch_zone

    # ── MACD ──────────────────────────────────────────────────
    macd_line = np.full(N, np.nan)
    macd_sig  = np.full(N, np.nan)
    macd_hist = np.full(N, np.nan)
    for i in range(35, N+1):
        mv, ms, mh = _macd(c[:i])
        if mv is not None:
            macd_line[i-1] = mv
            macd_sig[i-1]  = ms
            macd_hist[i-1] = mh
    df["MACD line"]      = macd_line
    df["MACD signal"]    = macd_sig
    df["MACD histogram"] = macd_hist
    macd_pos = np.full(N, np.nan, dtype=object)
    macd_pos[macd_line > macd_sig]  = "above signal"
    macd_pos[macd_line < macd_sig]  = "below signal"
    df["MACD position"] = macd_pos

    # ── MACD cross (عددی) ─────────────────────────────────────
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
    # صفر در بقیه حالت‌ها باقی می‌ماند (no cross)
    df["MACD cross"] = macd_cross

    # ── Bollinger Bands ───────────────────────────────────────
    bb_u = np.full(N, np.nan)
    bb_m = np.full(N, np.nan)
    bb_l = np.full(N, np.nan)
    bb_width = np.full(N, np.nan)
    bb_pos   = np.full(N, np.nan)
    for i in range(20, N+1):
        bu, bm, bl = _bollinger(c[:i], 20, 2.0)
        if bu is not None:
            bb_u[i-1] = bu
            bb_m[i-1] = bm
            bb_l[i-1] = bl
            bb_width[i-1] = (bu - bl) / bm * 100 if bm != 0 else np.nan
            bb_pos[i-1] = (c[i-1] - bl) / (bu - bl) * 100 if bu != bl else 50.0
    df["BB upper"]    = bb_u
    df["BB mid"]      = bb_m
    df["BB lower"]    = bb_l
    df["BB width %"]  = bb_width
    df["BB position"] = bb_pos

    bb_signal = np.full(N, np.nan, dtype=object)
    bb_signal[c > bb_u] = "above upper"
    bb_signal[c < bb_l] = "below lower"
    bb_signal[(c >= bb_l) & (c <= bb_u)] = "inside bands"
    df["BB signal"] = bb_signal
    df["BB squeeze"] = np.where(bb_width < 2.0, "yes", "no")

    # ── ATR ───────────────────────────────────────────────────
    atr_abs = np.full(N, np.nan)
    atr_pct = np.full(N, np.nan)
    for i in range(15, N+1):
        val = _atr(h[:i], l[:i], c[:i], 14)
        if val is not None:
            atr_abs[i-1] = val
            atr_pct[i-1] = val / c[i-1] if c[i-1] != 0 else np.nan
    df["ATR(14)"]      = atr_abs
    df["ATR % price"]  = atr_pct

    # ── Volume ────────────────────────────────────────────────
    df["Volume"] = v
    vol_avg = np.full(N, np.nan)
    for i in range(20, N):
        vol_avg[i] = v[i-19:i+1].mean()
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

    # ── Volume trend (عددی) ───────────────────────────────────
    vol_trend = np.zeros(N)
    if N >= 10:
        for i in range(10, N+1):
            cur5 = v[i-5:i].mean()
            prev5 = v[i-10:i-5].mean()
            if cur5 > prev5 * 1.1:
                vol_trend[i-1] = 1
            elif cur5 < prev5 * 0.9:
                vol_trend[i-1] = -1
    df["Volume trend"] = vol_trend

    # ── OBV trend (عددی) ──────────────────────────────────────
    obv_trend = np.full(N, np.nan)
    for i in range(6, N+1):
        trend = _obv_trend(c[:i], v[:i], lookback=5)
        if trend == "rising":
            obv_trend[i-1] = 1
        elif trend == "falling":
            obv_trend[i-1] = -1
        else:
            obv_trend[i-1] = 0
    df["OBV trend"] = obv_trend

    # ── Market structure (کل دوره) ────────────────────────────
    ms = _market_structure(c)
    df["Market structure"] = ms

    # ── Candle type & Engulfing ───────────────────────────────
    ct = np.full(N, None, dtype=object)
    for i in range(N):
        ct[i] = _candle_type(o[i], h[i], l[i], c[i])
    df["Candle type"] = ct

    engulf = np.full(N, None, dtype=object)
    for i in range(1, N):
        engulf[i] = _engulfing(o[i-1], c[i-1], o[i], c[i])
    df["Engulfing"] = engulf

    # ── Last 3 candles direction ──────────────────────────────
    last3 = np.full(N, None, dtype=object)
    for i in range(2, N):
        parts = []
        for j in range(i-2, i+1):
            parts.append("bull" if c[j] > o[j] else "bear")
        last3[i] = " → ".join(parts)
    df["Last 3 candles"] = last3

    # ── Distance to support / resistance (%) ──────────────────
    dist_support = np.full(N, np.nan)
    dist_resistance = np.full(N, np.nan)
    for i in range(50, N + 1):   # ۵۰ کندل حداقلی برای swing points
        sh, sl = _swing_points(h[:i], l[:i], lookback=3)
        levels = _nearest_levels(sh + sl, c[i-1], n=1)
        if levels["nearest_supports"]:
            sup = levels["nearest_supports"][0]
            dist_support[i-1] = (c[i-1] - sup) / c[i-1] * 100
        if levels["nearest_resistances"]:
            res = levels["nearest_resistances"][0]
            dist_resistance[i-1] = (res - c[i-1]) / c[i-1] * 100
    df["Distance to support %"] = dist_support
    df["Distance to resistance %"] = dist_resistance

    return df

def process_data(candles: list, current_price: float | None = None) -> list[dict[str, Any]]:
    """
    Convert raw kline list  [[ts, o, h, l, c, v], ...]
    → list[{"label": str, "value": any}]

    Candles are assumed oldest-first.
    `current_price` (optional) — real-time market price, used as the
    reference point for nearest support/resistance levels. Falls back
    to this timeframe's own last close if not provided.
    """
    if not candles or len(candles) < 2:
        return [{"label": "error", "value": "insufficient data"}]

    o = np.array([float(c[1]) for c in candles])
    h = np.array([float(c[2]) for c in candles])
    l = np.array([float(c[3]) for c in candles])
    c = np.array([float(c[4]) for c in candles])
    v = np.array([float(c[5]) for c in candles])

    result: list[dict] = []

    def r(label: str, value: Any) -> None:
        result.append({"label": label, "value": value})

    last_c = float(c[-1])
    prev_c = float(c[-2])

    # ── price snapshot ────────────────────────────────────────────────────────
    r("Close",    round(last_c,         8))
    r("Open",     round(float(o[-1]),   8))
    r("High",     round(float(h[-1]),   8))
    r("Low",      round(float(l[-1]),   8))
    r("Change %", round((last_c - prev_c) / prev_c * 100, 3))

    # ── period range ──────────────────────────────────────────────────────────
    p_high = float(h.max())
    p_low  = float(l.min())
    pos    = (last_c - p_low) / (p_high - p_low) * 100 if p_high != p_low else 50.0
    r("Period high",              round(p_high, 8))
    r("Period low",               round(p_low,  8))
    r("Position in period range", f"{round(pos, 1)}%")

    # ── EMAs ──────────────────────────────────────────────────────────────────
    emas: dict[int, float | None] = {}
    for period in (9, 21, 50, 200):
        e = _ema(c, period)
        if e is not None:
            val       = round(float(e[-1]), 8)
            diff_pct  = round((last_c - val) / val * 100, 2)
            emas[period] = val
            r(f"EMA{period}",          val)
            r(f"Price vs EMA{period}", f"{'+' if diff_pct >= 0 else ''}{diff_pct}%")
        else:
            emas[period] = None

    e9, e21, e50, e200 = emas.get(9), emas.get(21), emas.get(50), emas.get(200)

    if e9 and e21 and e50:
        if e9 > e21 > e50:   align = "bull (9>21>50)"
        elif e9 < e21 < e50: align = "bear (9<21<50)"
        else:                align = "mixed"
        r("EMA alignment", align)

    if e50 and e200:
        r("EMA50 vs EMA200",
          "golden cross zone" if e50 > e200 else "death cross zone")

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi = _rsi(c, 14)
    if rsi is not None:
        r("RSI(14)", rsi)
        r("RSI zone",
          "overbought"   if rsi >= 70 else
          "oversold"     if rsi <= 30 else
          "bullish zone" if rsi >= 55 else
          "bearish zone" if rsi <= 45 else
          "neutral")

    srsi = _stoch_rsi(c)
    if srsi is not None:
        r("Stoch RSI", srsi)
        r("Stoch RSI zone",
          "overbought" if srsi >= 80 else
          "oversold"   if srsi <= 20 else
          "neutral")

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_v, macd_s, macd_h = _macd(c)
    if macd_v is not None:
        r("MACD line",      macd_v)
        r("MACD signal",    macd_s)
        r("MACD histogram", macd_h)
        r("MACD position",  "above signal" if macd_v > macd_s else "below signal")

        prev_mv, prev_ms, _ = _macd(c[:-1])
        if prev_mv is not None:
            if   not (prev_mv > prev_ms) and (macd_v > macd_s): cross = "bullish_cross"
            elif (prev_mv > prev_ms) and not (macd_v > macd_s): cross = "bearish_cross"
            else:                                                cross = "none"
            r("MACD cross", cross)

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_u, bb_m, bb_l = _bollinger(c, 20, 2.0)
    if bb_u is not None:
        bb_width = round((bb_u - bb_l) / bb_m * 100, 2)
        bb_pos   = round((last_c - bb_l) / (bb_u - bb_l) * 100, 1) if bb_u != bb_l else 50.0
        r("BB upper",    round(bb_u, 8))
        r("BB mid",      round(bb_m, 8))
        r("BB lower",    round(bb_l, 8))
        r("BB width %",  bb_width)
        r("BB position", f"{bb_pos}%")
        r("BB signal",
          "above upper" if last_c > bb_u else
          "below lower" if last_c < bb_l else
          "inside bands")
        r("BB squeeze", "yes" if bb_width < 2.0 else "no")

    # ── ATR ───────────────────────────────────────────────────────────────────
    atr = _atr(h, l, c, 14)
    if atr is not None:
        r("ATR(14)",     atr)
        r("ATR % price", f"{round(atr / last_c * 100, 2)}%")

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_avg = float(v[-21:-1].mean()) if len(v) >= 21 else float(v[:-1].mean())
    vol_r   = round(float(v[-1]) / vol_avg, 2) if vol_avg else 1.0
    r("Volume",         round(float(v[-1]), 2))
    r("Volume avg(20)", round(vol_avg, 2))
    r("Volume ratio",   f"{vol_r}x")
    r("Volume signal",
      "very high"     if vol_r >= 2.0 else
      "above average" if vol_r >= 1.3 else
      "very low"      if vol_r <= 0.5 else
      "normal")

    if len(v) >= 10:
        r("Volume trend",
          "increasing" if v[-5:].mean() > v[-10:-5].mean() * 1.1 else
          "decreasing" if v[-5:].mean() < v[-10:-5].mean() * 0.9 else
          "flat")

    r("OBV trend", _obv_trend(c, v, lookback=5))

    # ── market structure ──────────────────────────────────────────────────────
    r("Market structure", _market_structure(c))

    # ── swing levels ─────────────────────────────────────────────────────────
    sh, sl = _swing_points(h, l, lookback=3)
    ref_price = current_price if current_price is not None else last_c
    levels = _nearest_levels(sh + sl, ref_price, n=3)
    if levels["nearest_resistances"]:
        r("Nearest resistances (closest first)", levels["nearest_resistances"])
    if levels["nearest_supports"]:
        r("Nearest supports (closest first)",    levels["nearest_supports"])

    # ── candle patterns ───────────────────────────────────────────────────────
    r("Last candle", _candle_type(float(o[-1]), float(h[-1]), float(l[-1]), last_c))

    eng = _engulfing(float(o[-2]), float(c[-2]), float(o[-1]), last_c)
    if eng:
        r("Engulfing", eng)

    r("Last 3 candles",
      " → ".join("bull" if c[i] > o[i] else "bear" for i in range(-3, 0)))

    # ── summary bias ──────────────────────────────────────────────────────────
    bull = bear = 0
    if rsi:
        if rsi > 55: bull += 1
        elif rsi < 45: bear += 1
    if macd_v:
        if macd_v > 0: bull += 1
        elif macd_v < 0: bear += 1
    if e9 and e21:
        if e9 > e21: bull += 1
        else:        bear += 1
    if last_c > prev_c: bull += 1
    else:               bear += 1
    if bb_m:
        if last_c > bb_m: bull += 1
        else:             bear += 1

    r("Bull signals", bull)
    r("Bear signals", bear)
    r("Bias",
      "bullish" if bull > bear else
      "bearish" if bear > bull else
      "neutral")

    return result

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