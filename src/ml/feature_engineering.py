""" src/ml/feature_engineering.py — Extract compressed features for ML training. """

import pandas as pd
import numpy as np
from typing import Dict, Any
from src.trading.rule_engine import SetupCandidate


class FeatureExtractor:
    """Extract all features required for the ML dataset schema."""

    @staticmethod
    def extract(candidate: SetupCandidate, df: pd.DataFrame) -> Dict[str, Any]:
        """Extract full feature set from a candidate and the latest data."""
        latest = df.iloc[-1]

        features = {
            # Setup metadata
            'setup_type': candidate.setup_type.value,
            'side': candidate.side,
            'timeframe': candidate.timeframe,

            # Trend features
            'higher_tf_bias': FeatureExtractor._higher_tf_bias(df),
            'market_structure': FeatureExtractor._market_structure(df),
            'ema_alignment': FeatureExtractor._ema_alignment(latest),
            'price_vs_ema9': (latest['Close'] - latest['ema_9']) / latest['ema_9'],
            'price_vs_ema21': (latest['Close'] - latest['ema_21']) / latest['ema_21'],
            'price_vs_ema50': (latest['Close'] - latest['ema_50']) / latest['ema_50'],

            # Momentum
            'rsi': latest.get('rsi', 50),
            'stoch_rsi': FeatureExtractor._stoch_rsi(df),
            'macd_position': latest.get('macd', 0),
            'macd_cross': 1 if latest.get('macd_hist', 0) > 0 else 0,

            # Volume
            'volume_ratio': latest.get('volume_ratio', 1),
            'volume_trend': FeatureExtractor._volume_trend(df),
            'obv_trend': FeatureExtractor._obv_trend(df),

            # Volatility
            'atr_percent': latest.get('atr_percent', 0),
            'bb_position': latest.get('bb_position', 0.5),
            'bb_width': latest.get('bb_width', 0),
            'bb_squeeze': 1 if latest.get('bb_width', 0) < df['bb_width'].rolling(20).min().iloc[-1] * 1.1 else 0,

            # Support/Resistance
            'distance_to_support': FeatureExtractor._distance_to_support(latest, df),
            'distance_to_resistance': FeatureExtractor._distance_to_resistance(latest, df),

            # Candle patterns
            'last_candle': FeatureExtractor._candle_pattern(df.iloc[-1], df.iloc[-2]),
            'engulfing': FeatureExtractor._engulfing(df.iloc[-1], df.iloc[-2]),

            # Signal counts
            'bull_signals': FeatureExtractor._bull_signals(latest),
            'bear_signals': FeatureExtractor._bear_signals(latest),
            'bias': 1 if latest['Close'] > latest['ema_50'] else 0,

            # Time features
            'hour_of_day': pd.Timestamp.now().hour,
            'day_of_week': pd.Timestamp.now().weekday(),
        }

        return features

    @staticmethod
    def _higher_tf_bias(df: pd.DataFrame) -> float:
        """Bias from higher timeframe (simplified: EMA slope)."""
        return 1.0 if df['ema_50'].iloc[-1] > df['ema_50'].iloc[-10] else 0.0

    @staticmethod
    def _market_structure(df: pd.DataFrame) -> str:
        """Identify market structure: uptrend, downtrend, ranging."""
        if df['ema_21'].iloc[-1] > df['ema_50'].iloc[-1] > df['ema_200'].iloc[-1]:
            return "uptrend"
        elif df['ema_21'].iloc[-1] < df['ema_50'].iloc[-1] < df['ema_200'].iloc[-1]:
            return "downtrend"
        return "ranging"

    @staticmethod
    def _ema_alignment(row: pd.Series) -> int:
        """Count of EMAs aligned (price > all = 3, price < all = -3)."""
        price = row['Close']
        score = 0
        for ema in ['ema_9', 'ema_21', 'ema_50']:
            if price > row[ema]:
                score += 1
            else:
                score -= 1
        return score

    @staticmethod
    def _stoch_rsi(df: pd.DataFrame) -> float:
        """Stochastic RSI (simplified)."""
        rsi = df['rsi']
        min_rsi = rsi.rolling(14).min()
        max_rsi = rsi.rolling(14).max()
        return (rsi.iloc[-1] - min_rsi.iloc[-1]) / (max_rsi.iloc[-1] - min_rsi.iloc[-1] + 1e-9) * 100

    @staticmethod
    def _volume_trend(df: pd.DataFrame) -> int:
        """Volume trend: 1 = increasing, -1 = decreasing, 0 = flat."""
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
        if vol_ma5 > vol_ma20 * 1.1:
            return 1
        elif vol_ma5 < vol_ma20 * 0.9:
            return -1
        return 0

    @staticmethod
    def _obv_trend(df: pd.DataFrame) -> int:
        """On-Balance Volume trend."""
        obv = (np.sign(df['Close'].diff()) * df['Volume']).cumsum()
        obv_slope = obv.iloc[-1] - obv.iloc[-10]
        return 1 if obv_slope > 0 else -1

    @staticmethod
    def _distance_to_support(row: pd.Series, df: pd.DataFrame) -> float:
        """Distance to nearest support (recent low)."""
        support = df['Low'].rolling(20).min().iloc[-1]
        return (row['Close'] - support) / row['Close']

    @staticmethod
    def _distance_to_resistance(row: pd.Series, df: pd.DataFrame) -> float:
        """Distance to nearest resistance (recent high)."""
        resistance = df['High'].rolling(20).max().iloc[-1]
        return (resistance - row['Close']) / row['Close']

    @staticmethod
    def _candle_pattern(current: pd.Series, prev: pd.Series) -> str:
        """Classify last candle."""
        if current['Close'] > current['Open']:
            if current['Close'] > prev['High']:
                return "bullish_breakout"
            return "bullish"
        else:
            if current['Close'] < prev['Low']:
                return "bearish_breakout"
            return "bearish"

    @staticmethod
    def _engulfing(current: pd.Series, prev: pd.Series) -> int:
        """Detect engulfing pattern."""
        if (prev['Close'] < prev['Open'] and  # previous bearish
            current['Close'] > current['Open'] and  # current bullish
            current['Open'] < prev['Close'] and
            current['Close'] > prev['Open']):
            return 1  # Bullish engulfing
        elif (prev['Close'] > prev['Open'] and  # previous bullish
              current['Close'] < current['Open'] and  # current bearish
              current['Open'] > prev['Close'] and
              current['Close'] < prev['Open']):
            return -1  # Bearish engulfing
        return 0

    @staticmethod
    def _bull_signals(row: pd.Series) -> int:
        """Count of bullish signals."""
        count = 0
        if row.get('rsi', 50) < 30: count += 1
        if row.get('macd_hist', 0) > 0: count += 1
        if row.get('volume_ratio', 1) > 1.5: count += 1
        if row.get('bb_position', 0.5) < 0.2: count += 1
        return count

    @staticmethod
    def _bear_signals(row: pd.Series) -> int:
        """Count of bearish signals."""
        count = 0
        if row.get('rsi', 50) > 70: count += 1
        if row.get('macd_hist', 0) < 0: count += 1
        if row.get('volume_ratio', 1) < 0.5: count += 1
        if row.get('bb_position', 0.5) > 0.8: count += 1
        return count