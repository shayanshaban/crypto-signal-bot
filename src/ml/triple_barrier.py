""" src/ml/triple_barrier.py — Triple Barrier labeling for trade outcomes. """

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class TradeRecord:
    """Record of a completed trade for labeling."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_timestamp: int
    exit_timestamp: int
    exit_price: float
    holding_candles: int


class TripleBarrierLabeler:
    """
    Apply Triple Barrier labeling to completed trades.
    
    Label = 1  → TP hit first
    Label = 0  → Time barrier hit first
    Label = -1 → SL hit first
    """

    def __init__(self, max_holding_bars: int = 30):
        self.max_holding_bars = max_holding_bars

    def label_trade(self, trade: TradeRecord, df: pd.DataFrame) -> int:
        """
        Determine which barrier was hit first using historical data.
        
        Args:
            trade: Completed trade record
            df: OHLCV dataframe covering the trade period
            
        Returns:
            1 (TP), 0 (Time), or -1 (SL)
        """
        # Find the slice of data from entry to exit
        entry_idx = df[df['Timestamp'] >= trade.entry_timestamp].index[0]
        exit_idx = df[df['Timestamp'] >= trade.exit_timestamp].index[0]

        # For each bar after entry, check if barriers were hit
        for i in range(entry_idx, min(exit_idx + 1, entry_idx + self.max_holding_bars)):
            high = df.loc[i, 'High']
            low = df.loc[i, 'Low']

            if trade.side == "LONG":
                # TP hit?
                if high >= trade.take_profit:
                    return 1
                # SL hit?
                if low <= trade.stop_loss:
                    return -1
            else:  # SHORT
                # TP hit? (price goes down)
                if low <= trade.take_profit:
                    return 1
                # SL hit? (price goes up)
                if high >= trade.stop_loss:
                    return -1

        # If neither barrier was hit within max_holding_bars
        return 0

    def label_batch(self, trades: list, df: pd.DataFrame) -> pd.DataFrame:
        """Label multiple trades and return as DataFrame."""
        results = []
        for trade in trades:
            label = self.label_trade(trade, df)
            results.append({
                'trade_id': id(trade),
                'triple_barrier': label,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'return_pct': (trade.exit_price - trade.entry_price) / trade.entry_price * 100,
                'pnl_r': (trade.exit_price - trade.entry_price) / (trade.stop_loss - trade.entry_price),
                'holding_candles': trade.holding_candles,
            })
        return pd.DataFrame(results)