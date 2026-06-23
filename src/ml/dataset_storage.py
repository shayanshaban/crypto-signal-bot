""" src/ml/dataset_storage.py — Store labeled trades as Apache Parquet. """

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from typing import Optional, List
from src.trading.rule_engine import SetupCandidate
from src.ml.feature_engineering import FeatureExtractor
from src.ml.triple_barrier import TradeRecord, TripleBarrierLabeler


class DatasetStorage:
    """Store ML dataset in Parquet format, organized by symbol and timeframe."""

    def __init__(self, base_dir: str = "dataset"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def store_trade(self, candidate: SetupCandidate, trade_record: TradeRecord,
                    features: dict, label: int, df: pd.DataFrame) -> None:
        """
        Store a single completed trade as a row in the dataset.
        """
        # Build the full row
        row = {
            # Trade metadata
            'trade_id': f"{candidate.symbol}_{trade_record.entry_timestamp}",
            'candle_ts': trade_record.entry_timestamp,
            'setup_type': candidate.setup_type.value,
            'side': candidate.side,
            'timeframe': candidate.timeframe,
            'higher_tf_bias': features.get('higher_tf_bias', 0),

            # Features (flattened)
            **{k: v for k, v in features.items() if k not in ['setup_type', 'side', 'timeframe']},

            # LLM decision
            'llm_decision': 1,  # 1 = confirmed, 0 = not (we only store executed trades)

            # Trade execution
            'entry_price': trade_record.entry_price,
            'stop_loss': trade_record.stop_loss,
            'take_profit': trade_record.take_profit,

            # Exit details
            'exit_price': trade_record.exit_price,
            'holding_candles': trade_record.holding_candles,

            # Performance
            'return_pct': (trade_record.exit_price - trade_record.entry_price) / trade_record.entry_price * 100,
            'pnl_r': (trade_record.exit_price - trade_record.entry_price) / (trade_record.stop_loss - trade_record.entry_price),

            # Label
            'triple_barrier': label,
        }

        # Convert to DataFrame
        df_row = pd.DataFrame([row])

        # Determine file path: dataset/{symbol}_{timeframe}.parquet
        filename = f"{candidate.symbol}_{candidate.timeframe}.parquet"
        filepath = self.base_dir / filename

        # Append or create
        if filepath.exists():
            existing = pd.read_parquet(filepath)
            combined = pd.concat([existing, df_row], ignore_index=True)
            combined.to_parquet(filepath, index=False)
        else:
            df_row.to_parquet(filepath, index=False)

    def load_dataset(self, symbol: Optional[str] = None,
                     timeframe: Optional[str] = None) -> pd.DataFrame:
        """Load dataset for a specific symbol/timeframe or all."""
        if symbol and timeframe:
            filepath = self.base_dir / f"{symbol}_{timeframe}.parquet"
            if filepath.exists():
                return pd.read_parquet(filepath)
            return pd.DataFrame()

        # Load all files
        all_dfs = []
        for f in self.base_dir.glob("*.parquet"):
            all_dfs.append(pd.read_parquet(f))
        if all_dfs:
            return pd.concat(all_dfs, ignore_index=True)
        return pd.DataFrame()