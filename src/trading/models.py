"""Domain models for the trading engine."""

from dataclasses import dataclass, field
from typing import Literal, Optional
from datetime import datetime
from .utils import generate_id, utc_now


@dataclass
class Position:
    """Represents a single futures position."""

    id: str = field(default_factory=generate_id)
    symbol: str = ""
    side: Literal["LONG", "SHORT"] = "LONG"
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    quantity: float = 0.0
    leverage: int = 1
    margin: float = 0.0
    risk_percent: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    fee_open: float = 0.0
    fee_close: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    status: Literal["OPEN", "CLOSED", "LIQUIDATED"] = "OPEN"
    created_at: datetime = field(default_factory=utc_now)
    closed_at: Optional[datetime] = None
    liquidation_price: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize position to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "leverage": self.leverage,
            "margin": self.margin,
            "risk_percent": self.risk_percent,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "fee_open": self.fee_open,
            "fee_close": self.fee_close,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "liquidation_price": self.liquidation_price,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        """Deserialize from a dictionary."""
        return cls(
            id=data["id"],
            symbol=data["symbol"],
            side=data["side"],
            entry_price=data["entry_price"],
            exit_price=data.get("exit_price"),
            quantity=data["quantity"],
            leverage=data["leverage"],
            margin=data["margin"],
            risk_percent=data["risk_percent"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            fee_open=data["fee_open"],
            fee_close=data["fee_close"],
            realized_pnl=data["realized_pnl"],
            unrealized_pnl=data["unrealized_pnl"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None,
            liquidation_price=data["liquidation_price"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class Wallet:
    """Aggregated wallet state."""

    balance: float = 0.0
    equity: float = 0.0
    used_margin: float = 0.0
    free_margin: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    number_of_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0
    peak_balance: float = 0.0
    open_positions: list[Position] = field(default_factory=list)
    closed_positions: list[Position] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize wallet to a dictionary."""
        return {
            "balance": self.balance,
            "equity": self.equity,
            "used_margin": self.used_margin,
            "free_margin": self.free_margin,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_fees": self.total_fees,
            "number_of_trades": self.number_of_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "max_drawdown": self.max_drawdown,
            "peak_balance": self.peak_balance,
            "open_positions": [pos.to_dict() for pos in self.open_positions],
            "closed_positions": [pos.to_dict() for pos in self.closed_positions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Wallet":
        """Deserialize from a dictionary."""
        return cls(
            balance=data["balance"],
            equity=data["equity"],
            used_margin=data["used_margin"],
            free_margin=data["free_margin"],
            realized_pnl=data["realized_pnl"],
            unrealized_pnl=data["unrealized_pnl"],
            total_fees=data["total_fees"],
            number_of_trades=data["number_of_trades"],
            winning_trades=data["winning_trades"],
            losing_trades=data["losing_trades"],
            max_drawdown=data["max_drawdown"],
            peak_balance=data["peak_balance"],
            open_positions=[Position.from_dict(p) for p in data["open_positions"]],
            closed_positions=[Position.from_dict(p) for p in data["closed_positions"]],
        )