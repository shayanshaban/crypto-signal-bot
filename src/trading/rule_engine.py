""" src/trading/rule_engine.py — Rule-based setup detection with hard filters. """

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class SetupType(Enum):
    TREND_PULLBACK = "trend_pullback"
    BREAKOUT = "breakout"
    EMA_CROSS = "ema_cross"
    MEAN_REVERSION = "mean_reversion"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    BB_SQUEEZE_BREAKOUT = "bb_squeeze_breakout"


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
    """Detects trading setups using deterministic rules + hard filters."""

    def __init__(self, min_atr_threshold: float = 0.01,
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

        # Calculate all indicators once
        df = self._add_indicators(df)

        # Detect each setup type
        candidates.extend(self._detect_trend_pullback(df, symbol, timeframe))
        candidates.extend(self._detect_breakout(df, symbol, timeframe))
        candidates.extend(self._detect_ema_cross(df, symbol, timeframe))
        candidates.extend(self._detect_mean_reversion(df, symbol, timeframe))
        candidates.extend(self._detect_liquidity_sweep(df, symbol, timeframe))
        candidates.extend(self._detect_bb_squeeze_breakout(df, symbol, timeframe))

        # Apply hard filters
        return [c for c in candidates if self._passes_hard_filters(c, df)]

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical indicators needed for setup detection."""
        df = df.copy()

        # EMAs
        for period in [9, 21, 50, 200]:
            df[f'ema_{period}'] = df['Close'].ewm(span=period, adjust=False).mean()

        # ATR
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_percent'] = df['atr'] / df['Close'] * 100

        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        df['bb_middle'] = df['Close'].rolling(20).mean()
        bb_std = df['Close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * bb_std
        df['bb_lower'] = df['bb_middle'] - 2 * bb_std
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        df['bb_position'] = (df['Close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # Volume
        df['volume_ma'] = df['Volume'].rolling(20).mean()
        df['volume_ratio'] = df['Volume'] / df['volume_ma']

        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        return df

    def _detect_trend_pullback(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Detect pullback to EMA in an established trend."""
        candidates = []
        latest = df.iloc[-1]

        # Trend: price above EMA50 and EMA50 > EMA200
        if not (latest['Close'] > latest['ema_50'] > latest['ema_200']):
            return candidates

        # Pullback: price near EMA21 (within 0.5%)
        pullback = abs(latest['Close'] - latest['ema_21']) / latest['ema_21'] < 0.005

        if pullback:
            candidates.append(SetupCandidate(
                setup_type=SetupType.TREND_PULLBACK,
                symbol=symbol,
                side="LONG",
                timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=latest['Close'] * 0.98,  # 2% stop
                take_profit=latest['Close'] * 1.04,  # 4% target
                features=self._extract_features(latest),
                timestamp=int(latest.name.timestamp()) if hasattr(latest.name, 'timestamp') else 0
            ))
        return candidates

    def _detect_breakout(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Detect breakout above resistance with volume confirmation."""
        candidates = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Find recent resistance (highest high of last 20 bars)
        resistance = df['High'].rolling(20).max().iloc[-2]

        # Breakout: close above resistance + volume spike
        if latest['Close'] > resistance and latest['volume_ratio'] > 1.5:
            candidates.append(SetupCandidate(
                setup_type=SetupType.BREAKOUT,
                symbol=symbol,
                side="LONG",
                timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=resistance * 0.99,
                take_profit=latest['Close'] * 1.03,
                features=self._extract_features(latest),
                timestamp=int(latest.name.timestamp()) if hasattr(latest.name, 'timestamp') else 0
            ))
        return candidates

    def _detect_ema_cross(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Detect EMA9 crossing above EMA21."""
        candidates = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        if (prev['ema_9'] <= prev['ema_21'] and
            latest['ema_9'] > latest['ema_21'] and
            latest['volume_ratio'] > 1.2):
            candidates.append(SetupCandidate(
                setup_type=SetupType.EMA_CROSS,
                symbol=symbol,
                side="LONG",
                timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=latest['Close'] * 0.985,
                take_profit=latest['Close'] * 1.035,
                features=self._extract_features(latest),
                timestamp=int(latest.name.timestamp()) if hasattr(latest.name, 'timestamp') else 0
            ))
        return candidates

    def _detect_mean_reversion(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Detect oversold bounce setup."""
        candidates = []
        latest = df.iloc[-1]

        # RSI < 30 and price near lower BB
        if latest['rsi'] < 30 and latest['bb_position'] < 0.1:
            candidates.append(SetupCandidate(
                setup_type=SetupType.MEAN_REVERSION,
                symbol=symbol,
                side="LONG",
                timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=latest['Close'] * 0.99,
                take_profit=latest['bb_middle'],
                features=self._extract_features(latest),
                timestamp=int(latest.name.timestamp()) if hasattr(latest.name, 'timestamp') else 0
            ))
        return candidates

    def _detect_liquidity_sweep(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Detect sweep of recent lows with reversal."""
        candidates = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Sweep: price breaks below recent low then closes back above
        recent_low = df['Low'].rolling(20).min().iloc[-2]
        if (prev['Low'] < recent_low and
            latest['Close'] > recent_low and
            latest['Close'] > latest['ema_21']):
            candidates.append(SetupCandidate(
                setup_type=SetupType.LIQUIDITY_SWEEP,
                symbol=symbol,
                side="LONG",
                timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=recent_low * 0.995,
                take_profit=latest['Close'] * 1.03,
                features=self._extract_features(latest),
                timestamp=int(latest.name.timestamp()) if hasattr(latest.name, 'timestamp') else 0
            ))
        return candidates

    def _detect_bb_squeeze_breakout(self, df: pd.DataFrame, symbol: str, tf: str) -> List[SetupCandidate]:
        """Detect Bollinger Band squeeze followed by breakout."""
        candidates = []
        latest = df.iloc[-1]

        # Squeeze: BB width near 20-period minimum
        bb_width_20 = df['bb_width'].rolling(20).min().iloc[-2]
        if (df['bb_width'].iloc[-2] < bb_width_20 * 1.1 and
            latest['bb_width'] > bb_width_20 * 1.2 and
            latest['volume_ratio'] > 1.5):
            candidates.append(SetupCandidate(
                setup_type=SetupType.BB_SQUEEZE_BREAKOUT,
                symbol=symbol,
                side="LONG" if latest['Close'] > latest['bb_middle'] else "SHORT",
                timeframe=tf,
                entry_price=latest['Close'],
                stop_loss=latest['Close'] * 0.985 if latest['Close'] > latest['bb_middle'] else latest['Close'] * 1.015,
                take_profit=latest['Close'] * 1.04 if latest['Close'] > latest['bb_middle'] else latest['Close'] * 0.96,
                features=self._extract_features(latest),
                timestamp=int(latest.name.timestamp()) if hasattr(latest.name, 'timestamp') else 0
            ))
        return candidates

    def _extract_features(self, row: pd.Series) -> Dict[str, Any]:
        """Extract a minimal feature dict from a row."""
        return {
            'rsi': row.get('rsi', 50),
            'atr_percent': row.get('atr_percent', 0),
            'volume_ratio': row.get('volume_ratio', 1),
            'bb_position': row.get('bb_position', 0.5),
            'bb_width': row.get('bb_width', 0),
            'macd_hist': row.get('macd_hist', 0),
        }

    def _passes_hard_filters(self, candidate: SetupCandidate, df: pd.DataFrame) -> bool:
        """Apply deterministic hard filters before LLM."""
        latest = df.iloc[-1]

        # ATR threshold
        if latest.get('atr_percent', 0) < self.min_atr_threshold:
            return False

        # Volume ratio
        if latest.get('volume_ratio', 0) < self.min_volume_ratio:
            return False

        # Trend alignment (for LONG setups)
        if self.trend_alignment_required and candidate.side == "LONG":
            if latest.get('ema_50', 0) <= latest.get('ema_200', 0):
                return False

        return True