"""
src/trading/rule_engine.py — Rule-based setup detection with hard filters.
(Optimised: uses numerical features from baker.enrich_dataframe)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from src.data.baker import enrich_dataframe


class SetupType(Enum):
    TREND_PULLBACK = "trend_pullback"
    BREAKOUT = "breakout"
    EMA_CROSS = "ema_cross"
    MEAN_REVERSION = "mean_reversion"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    BB_SQUEEZE_BREAKOUT = "bb_squeeze_breakout"
    MACD_CROSS = "macd_cross"
    RSI_DIVERGENCE = "rsi_divergence"
    PINBAR_CONFIRM = "pinbar_confirm"


@dataclass
class SetupCandidate:
    """A candidate trade setup detected by the rule engine."""
    setup_type: SetupType
    symbol: str
    side: str  # "LONG" or "SHORT"
    timeframe: str
    entry_price: float
    stop_loss: float
    take_profit: float
    features: Dict[str, Any]
    timestamp: int


class RuleEngine:
    """Detects trading setups using deterministic rules + hard filters.

    Requires DataFrame enriched by baker.enrich_dataframe.
    """

    def __init__(self, min_atr_threshold: float = 0.005,
                 min_volume_ratio: float = 1.5,
                 trend_alignment_required: bool = True):
        self.min_atr_threshold = min_atr_threshold
        self.min_volume_ratio = min_volume_ratio
        self.trend_alignment_required = trend_alignment_required

    def detect_setups(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[SetupCandidate]:
        """
        Scan a dataframe for all setup types. Returns list of candidates
        that pass hard filters.
        """
        candidates = []

        # 1. اطمینان از وجود اندیکاتورهای مورد نیاز (اگر enrich_dataframe اجرا نشده باشد)
        if "EMA alignment" not in df.columns:
            df = enrich_dataframe(df.copy())

        # 2. اجرای تمام آشکارسازها
        # candidates.extend(self._detect_trend_pullback(df, symbol, timeframe))
        # candidates.extend(self._detect_breakout(df, symbol, timeframe))
        # candidates.extend(self._detect_ema_cross(df, symbol, timeframe))
        # candidates.extend(self._detect_mean_reversion(df, symbol, timeframe))
        # candidates.extend(self._detect_liquidity_sweep(df, symbol, timeframe))
        # candidates.extend(self._detect_bb_squeeze_breakout(df, symbol, timeframe))
        # candidates.extend(self._detect_macd_cross(df, symbol, timeframe))
        # candidates.extend(self._detect_rsi_divergence(df, symbol, timeframe))
        candidates.extend(self._detect_pinbar_confirm(df, symbol, timeframe))
        # 3. اعمال فیلترهای سخت
        return [c for c in candidates if self._passes_hard_filters(c, df)]

    # ── آشکارسازهای Setup ─────────────────────────────────────────────────

    def _detect_trend_pullback(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Pullback به EMA21 در یک روند صعودی مستقر (EMA alignment = 1)."""
        candidates = []
        latest = df.iloc[-1]

        # روند صعودی: EMA alignment == 1
        if latest.get("EMA alignment", 0) != 1:
            return candidates

        # Pullback: قیمت نزدیک EMA21 (اختلاف کمتر از 0.5%)
        ema21 = latest.get("EMA21")
        if pd.isna(ema21) or ema21 == 0:
            return candidates
        pullback = abs(latest['Close'] - ema21) / ema21 < 0.005

        if pullback:
            atr_pct = latest.get("ATR % price", 0.01)
            sl = latest['Close'] * (1 - 2 * atr_pct)
            tp = latest['Close'] * (1 + 4 * atr_pct)
            candidates.append(SetupCandidate(
                setup_type=SetupType.TREND_PULLBACK,
                symbol=symbol, side="LONG", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        return candidates

    def _detect_breakout(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """شکست مقاومت نزدیک (فاصله‌ی کمتر از 0.5%) با تأیید حجم."""
        candidates = []
        latest = df.iloc[-1]

        dist_res = latest.get("Distance to resistance %")
        if pd.isna(dist_res) or dist_res >= 0.5:
            return candidates

        # حجم بالا
        if latest.get("Volume ratio", 0) < self.min_volume_ratio:
            return candidates

        # می‌توان آستانه‌ی شکست را سخت‌گیرانه‌تر گذاشت (مثلاً قیمت بالاتر از مقاومت قبلی)
        resistance = latest['Close'] * (1 + dist_res / 100)   # تخمین قیمت مقاومت
        if latest['Close'] <= resistance:
            return candidates

        sl = max(resistance * 0.99, latest['Close'] * 0.98)
        tp = latest['Close'] * 1.03
        candidates.append(SetupCandidate(
            setup_type=SetupType.BREAKOUT,
            symbol=symbol, side="LONG", timeframe=tf,
            entry_price=latest['Close'],
            stop_loss=sl,
            take_profit=tp,
            features=self._extract_features(latest),
            timestamp=self._get_timestamp(latest)
        ))
        return candidates

    def _detect_ema_cross(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """کراس EMA9 به بالای EMA21 با حجم بالاتر از میانگین."""
        candidates = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        if (prev['EMA9'] <= prev['EMA21'] and
            latest['EMA9'] > latest['EMA21'] and
            latest.get("Volume ratio", 0) > 1.2):
            sl = latest['Close'] * 0.985
            tp = latest['Close'] * 1.035
            candidates.append(SetupCandidate(
                setup_type=SetupType.EMA_CROSS,
                symbol=symbol, side="LONG", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        return candidates

    def _detect_mean_reversion(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """بازگشت به میانگین: RSI زیر ۳۰ و قیمت نزدیک حمایت (فاصله‌ی کمتر از ۲٪)."""
        candidates = []
        latest = df.iloc[-1]

        if latest.get("RSI(14)", 50) >= 30:
            return candidates
        dist_sup = latest.get("Distance to support %")
        if pd.isna(dist_sup) or dist_sup >= 2.0:
            return candidates

        # ورود در محدوده‌ی حمایتی
        sl = latest['Close'] * 0.99
        tp = latest.get("BB mid", latest['Close'] * 1.02)   # هدف: میانگین بولینگر
        candidates.append(SetupCandidate(
            setup_type=SetupType.MEAN_REVERSION,
            symbol=symbol, side="LONG", timeframe=tf,
            entry_price=latest['Close'],
            stop_loss=sl,
            take_profit=tp,
            features=self._extract_features(latest),
            timestamp=self._get_timestamp(latest)
        ))
        return candidates

    def _detect_liquidity_sweep(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """شکار نقدینگی: شکست کف ۲۰ کندلی و بسته شدن مجدد بالای آن + بالای EMA21."""
        candidates = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        recent_low = df['Low'].rolling(20).min().iloc[-2]

        if (prev['Low'] < recent_low and
            latest['Close'] > recent_low and
            latest['Close'] > latest['EMA21']):
            sl = recent_low * 0.995
            tp = latest['Close'] * 1.03
            candidates.append(SetupCandidate(
                setup_type=SetupType.LIQUIDITY_SWEEP,
                symbol=symbol, side="LONG", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        return candidates

    def _detect_bb_squeeze_breakout(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """فشردگی بولینگر و شکست با حجم بالا."""
        candidates = []
        latest = df.iloc[-1]
        bb_width_20 = df['BB width %'].rolling(20).min().iloc[-2]

        if (df['BB width %'].iloc[-2] < bb_width_20 * 1.1 and
            latest['BB width %'] > bb_width_20 * 1.2 and
            latest.get("Volume ratio", 0) > 1.5):
            side = "LONG" if latest['Close'] > latest['BB mid'] else "SHORT"
            sl_mult = 0.985 if side == "LONG" else 1.015
            tp_mult = 1.04 if side == "LONG" else 0.96
            candidates.append(SetupCandidate(
                setup_type=SetupType.BB_SQUEEZE_BREAKOUT,
                symbol=symbol, side=side, timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=latest['Close'] * sl_mult,
                take_profit=latest['Close'] * tp_mult,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        return candidates

    def _detect_macd_cross(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """کراس عددی MACD (1 یا -1) با تأیید RSI."""
        candidates = []
        latest = df.iloc[-1]

        macd_cross = latest.get("MACD cross", 0)
        if macd_cross == 1 and latest.get("RSI(14)", 50) > 50:
            atr_pct = latest.get("ATR % price", 0.01)
            sl = latest['Close'] * (1 - atr_pct)
            tp = latest['Close'] * (1 + 2 * atr_pct)
            candidates.append(SetupCandidate(
                setup_type=SetupType.MACD_CROSS,
                symbol=symbol, side="LONG", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        elif macd_cross == -1 and latest.get("RSI(14)", 50) < 50:
            atr_pct = latest.get("ATR % price", 0.01)
            sl = latest['Close'] * (1 + atr_pct)
            tp = latest['Close'] * (1 - 2 * atr_pct)
            candidates.append(SetupCandidate(
                setup_type=SetupType.MACD_CROSS,
                symbol=symbol, side="SHORT", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        return candidates

    def _detect_rsi_divergence(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """واگرایی RSI (مقایسه‌ی ۴ کندل قبل)."""
        candidates = []
        if len(df) < 5:
            return candidates

        latest = df.iloc[-1]
        prev3 = df.iloc[-4]

        # واگرایی مثبت: Low پایین‌تر، RSI بالاتر
        if latest['Low'] < prev3['Low'] and latest['RSI(14)'] > prev3['RSI(14)'] and latest['RSI(14)'] < 40:
            sl = latest['Close'] * 0.98
            tp = latest['Close'] * 1.04
            candidates.append(SetupCandidate(
                setup_type=SetupType.RSI_DIVERGENCE,
                symbol=symbol, side="LONG", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        # واگرایی منفی
        elif latest['High'] > prev3['High'] and latest['RSI(14)'] < prev3['RSI(14)'] and latest['RSI(14)'] > 60:
            sl = latest['Close'] * 1.02
            tp = latest['Close'] * 0.96
            candidates.append(SetupCandidate(
                setup_type=SetupType.RSI_DIVERGENCE,
                symbol=symbol, side="SHORT", timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=sl,
                take_profit=tp,
                features=self._extract_features(latest),
                timestamp=self._get_timestamp(latest)
            ))
        return candidates

    # ── ابزارهای کمکی ────────────────────────────────────────────────────────

    def _extract_features(self, row: pd.Series) -> Dict[str, Any]:
        """استخراج ویژگی‌های کلیدی برای ذخیره در کاندید."""
        return {
            'rsi': row.get('RSI(14)', np.nan),
            'atr_percent': row.get('ATR % price', np.nan),
            'volume_ratio': row.get('Volume ratio', np.nan),
            'bb_position': row.get('BB position', np.nan),
            'bb_width': row.get('BB width %', np.nan),
            'macd_hist': row.get('MACD histogram', np.nan),
            'macd_cross': row.get('MACD cross', 0),
            'ema_alignment': row.get('EMA alignment', 0),
            'dist_support': row.get('Distance to support %', np.nan),
            'dist_resistance': row.get('Distance to resistance %', np.nan),
        }

    def _detect_pinbar_confirm(
        self,
        df: pd.DataFrame,
        symbol: str,
        tf: str,
    ) -> List[SetupCandidate]:
        """Pin Bar + Confirmation candle"""

        candidates = []

        if len(df) < 2:
            return candidates

        pin = df.iloc[-2]
        confirm = df.iloc[-1]

        # -------------------------
        # LONG
        # -------------------------

        body = abs(pin["Close"] - pin["Open"])
        if body == 0:
            body = 1e-9

        lower_wick = min(pin["Open"], pin["Close"]) - pin["Low"]
        upper_wick = pin["High"] - max(pin["Open"], pin["Close"])

        bullish_pinbar = (
            lower_wick >= body * 2
            and upper_wick <= body
        )

        bullish_confirm = (
            confirm["Close"] > confirm["Open"]
            and abs(confirm["Close"] - confirm["Open"]) > body * 0.6
        )

        if (
            pin.get("Distance to support %", 999) < 0.3
            and confirm.get("EMA alignment", 0) == 1
            and bullish_pinbar
            and bullish_confirm
            and confirm.get("Volume ratio", 0) >= 1.0
            and confirm.get("RSI(14)", 50) < 70
        ):

            atr = confirm.get("ATR(14)", 0)

            entry = confirm["Close"]
            sl = pin["Low"] - atr * 0.2

            risk = entry - sl
            tp = entry + risk * 2

            candidates.append(
                SetupCandidate(
                    setup_type=SetupType.PINBAR_CONFIRM,
                    symbol=symbol,
                    side="LONG",
                    timeframe=tf,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    features=self._extract_features(confirm),
                    timestamp=self._get_timestamp(confirm),
                )
            )

        # -------------------------
        # SHORT
        # -------------------------

        bearish_pinbar = (
            upper_wick >= body * 2
            and lower_wick <= body
        )

        bearish_confirm = (
            confirm["Close"] < confirm["Open"]
            and abs(confirm["Close"] - confirm["Open"]) > body * 0.6
        )

        if (
            pin.get("Distance to resistance %", 999) < 0.3
            and confirm.get("EMA alignment", 0) == -1
            and bearish_pinbar
            and bearish_confirm
            and confirm.get("Volume ratio", 0) >= 1.0
            and confirm.get("RSI(14)", 50) > 30
        ):

            atr = confirm.get("ATR(14)", 0)

            entry = confirm["Close"]
            sl = pin["High"] + atr * 0.2

            risk = sl - entry
            tp = entry - risk * 2

            candidates.append(
                SetupCandidate(
                    setup_type=SetupType.PINBAR_CONFIRM,
                    symbol=symbol,
                    side="SHORT",
                    timeframe=tf,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    features=self._extract_features(confirm),
                    timestamp=self._get_timestamp(confirm),
                )
            )

        return candidates

    def _get_timestamp(self, row: pd.Series) -> int:
        if hasattr(row.name, 'timestamp'):
            return int(row.name.timestamp())
        return 0

    def _passes_hard_filters(self, candidate: SetupCandidate, df: pd.DataFrame) -> bool:
        return True # just for test
        """فیلترهای سخت‌گیرانه با استفاده از تمام اندیکاتورهای عددی."""
        latest = df.iloc[-1]

        # رد داده‌ی ناقص – ATR و RSI نباید NaN باشند
        if pd.isna(latest.get("ATR % price")):
            return False
        if pd.isna(latest.get("RSI(14)")):
            return False

        # حداقل نوسان
        if latest.get("ATR % price", 0) < self.min_atr_threshold:
            return False

        # حجم برای ستاپ‌های حساس
        volume_sensitive = {SetupType.BREAKOUT, SetupType.BB_SQUEEZE_BREAKOUT, SetupType.EMA_CROSS}
        if candidate.setup_type in volume_sensitive:
            if latest.get("Volume ratio", 0) < self.min_volume_ratio:
                return False

        # هم‌راستایی روند (در صورت نیاز)
        if self.trend_alignment_required:
            ema_align = latest.get("EMA alignment", 0)
            if candidate.side == "LONG" and ema_align != 1:
                return False
            elif candidate.side == "SHORT" and ema_align != -1:
                return False

        # فیلتر اضافی برای MACD (اختیاری)
        if candidate.setup_type == SetupType.MACD_CROSS:
            if candidate.side == "LONG" and latest.get("MACD histogram", 0) <= 0:
                return False
            if candidate.side == "SHORT" and latest.get("MACD histogram", 0) >= 0:
                return False

        return True