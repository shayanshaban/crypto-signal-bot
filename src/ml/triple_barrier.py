"""src/ml/triple_barrier.py — Triple Barrier labeling for trade outcomes."""

import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class TradeRecord:
    symbol: str
    side: str          # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_timestamp: int
    exit_timestamp: int
    exit_price: float
    holding_candles: int


class TripleBarrierLabeler:
    """
    Label = 1  → TP hit first
    Label = 0  → Time barrier hit first
    Label = -1 → SL hit first
    """

    def __init__(self, max_holding_bars: int = 30):
        self.max_holding_bars = max_holding_bars

    def label_trade(self, trade: TradeRecord, df: pd.DataFrame) -> int:
        """
        df می‌تونه هر index و هر ستون timestamp ای داشته باشه.
        فقط High و Low لازمه.
        """
        if df is None or df.empty:
            return 0

        # ── پیدا کردن timestamp column ────────────────────────
        ts_col = None
        for name in ("Timestamp", "timestamp", "time", "Time", "date", "Date"):
            if name in df.columns:
                ts_col = name
                break

        # ── برش df از entry تا exit ───────────────────────────
        if ts_col is not None:
            mask = (df[ts_col] >= trade.entry_timestamp) & \
                   (df[ts_col] <= trade.exit_timestamp)
            df_slice = df[mask].reset_index(drop=True)
        else:
            # اگه timestamp نبود، کل df رو بگیر (قبلاً slice شده)
            df_slice = df.reset_index(drop=True)

        if df_slice.empty:
            return 0

        # ── چک ستون‌های High/Low ──────────────────────────────
        high_col = next((c for c in ("High", "high") if c in df_slice.columns), None)
        low_col  = next((c for c in ("Low",  "low")  if c in df_slice.columns), None)

        if high_col is None or low_col is None:
            return 0

        # ── Triple Barrier ────────────────────────────────────
        max_bars = min(self.max_holding_bars, len(df_slice))

        for i in range(max_bars):
            high = df_slice.loc[i, high_col]
            low  = df_slice.loc[i, low_col]

            if trade.side.upper() == "LONG":
                if high >= trade.take_profit:
                    return 1
                if low  <= trade.stop_loss:
                    return -1
            else:  # SHORT
                if low  <= trade.take_profit:
                    return 1
                if high >= trade.stop_loss:
                    return -1

        return 0  # time barrier

    def label_batch(self, trades: list, df: pd.DataFrame) -> pd.DataFrame:
        results = []
        for trade in trades:
            label = self.label_trade(trade, df)
            entry = trade.entry_price
            sl    = trade.stop_loss
            exit_ = trade.exit_price
            results.append({
                "triple_barrier":  label,
                "entry_price":     entry,
                "exit_price":      exit_,
                "return_pct":      (exit_ - entry) / entry * 100 if entry else 0,
                "pnl_r":           (exit_ - entry) / (sl - entry) if sl != entry else 0,
                "holding_candles": trade.holding_candles,
            })
        return pd.DataFrame(results)