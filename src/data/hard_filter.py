"""
فیلترهای سخت — بعد از تشخیص ستاپ، قبل از AI.
اگه هر کدوم fail بشه، AI صدا زده نمی‌شه.
"""
import numpy as np
from src.data.baker import _atr
from src.data.setup_detector import Setup


def check(candles: list, setup: Setup) -> bool:
    """True = همه فیلترها پاس شدن، برو سراغ AI."""
    if not candles or len(candles) < 20:
        return False

    c = np.array([float(x[4]) for x in candles])
    h = np.array([float(x[2]) for x in candles])
    l = np.array([float(x[3]) for x in candles])
    v = np.array([float(x[5]) for x in candles])

    last_c  = float(c[-1])
    vol_avg = float(v[-21:-1].mean()) if len(v) >= 21 else float(v[:-1].mean())

    # فیلتر ۱: حجم حداقل ۱.۲ برابر میانگین
    if vol_avg > 0 and float(v[-1]) / vol_avg < 1.2:
        return False

    # فیلتر ۲: نوسان‌پذیری کافی (ATR حداقل ۰.۳٪ قیمت)
    atr = _atr(h, l, c, 14)
    if atr is None or last_c == 0:
        return False
    if atr / last_c * 100 < 0.3:
        return False

    # فیلتر ۳: فاصله از مقاومت نزدیک (برای LONG، باید فضا داشته باشیم)
    # این فیلتر سخت نیست — فقط اگه setup direction مشخص بود اعمال می‌شه
    # (می‌شه بعداً بر اساس swing points دقیق‌تر کرد)

    return True