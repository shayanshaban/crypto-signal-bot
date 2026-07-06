"""
Thread-safe JSONL trade logger.
Every trade event (open, close, liquidation, etc.) is appended as one JSON line.
"""

import json
import threading
from datetime import datetime
from .utils import utc_now


class TradeLogger:
    """Logs trading events to a JSONL file."""

    def __init__(self, filepath: str = "logs/trades.jsonl"):
        self.filepath = filepath
        self._lock = threading.Lock()
        self._ensure_file()

    def log_event(
        self,
        event: str,
        position_id: str,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        fee: float,
        pnl: float,
        balance: float,
        equity: float,
        reason: str = "",
    ) -> None:
        """
        Append a structured event record to the log file.
        """
        record = {
            "timestamp": utc_now().isoformat(),
            "event": event,
            "position_id": position_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": quantity,
            "fee": fee,
            "pnl": pnl,
            "balance": balance,
            "equity": equity,
            "reason": reason,
        }
        with self._lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def _ensure_file(self):
        """Create the log file if it doesn't exist."""
        from pathlib import Path
        path = Path(self.filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()