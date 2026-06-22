"""
src/data/baker.py — Compress raw OHLCV candles into labeled indicators.

Public API:
  process_data(candles)  — list[[ts,o,h,l,c,v]] → list[{"label", "value"}]
"""

from __future__ import annotations
import numpy as np
from typing import Any


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