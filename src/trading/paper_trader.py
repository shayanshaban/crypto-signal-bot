"""Paper trading engine – simulates order execution without a real exchange."""

from __future__ import annotations
import copy
from typing import Optional
from .models import Position, Wallet
from .wallet import WalletManager
from .risk_manager import RiskManager
from .trade_logger import TradeLogger
from .exceptions import (
    TradingException,
    PositionException,
    MarginException,
)
from .constants import DEFAULT_SLIPPAGE, FEE_RATE
from .utils import round_price, utc_now


class PaperTrader:
    """
    Simulates futures trading with full wallet accounting,
    risk management, and logging.

    This class uses the same interfaces that a real exchange trader would,
    making it trivial to swap implementations later.
    """

    def __init__(
        self,
        wallet_manager: WalletManager,
        risk_manager: RiskManager,
        logger: TradeLogger,
    ):
        self.wallet_manager = wallet_manager
        self.risk_manager = risk_manager
        self.logger = logger

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------
    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        risk_percent: float,
        leverage: int,
        slippage_rate: float = DEFAULT_SLIPPAGE,
    ) -> Position:
        """
        Validate, size, and open a new position.

        Parameters
        ----------
        symbol : str
            Trading pair, e.g. "BTCUSDT".
        side : str
            "LONG" or "SHORT".
        entry_price : float
            Market (quoted) price at which the order is triggered.
            Actual fill price is adjusted by slippage_rate.
        stop_loss : float
            Stop-loss trigger price.
        take_profit : float
            Take-profit trigger price.
        risk_percent : float
            Fraction of balance to risk (0.0-1.0).
        leverage : int
            Leverage multiplier.
        slippage_rate : float
            Slippage fraction applied to execution price.

        Returns
        -------
        Position
            The newly created OPEN position.
        """
        # --- Pre-validation (against quoted entry_price, before slippage) ---
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            raise ValueError("Prices must be positive.")
        if risk_percent <= 0 or risk_percent > 1:
            raise ValueError("risk_percent must be in (0, 1].")
        if leverage <= 0:
            raise ValueError("Leverage must be positive.")

        if side == "LONG":
            if stop_loss >= entry_price:
                raise ValueError("LONG stop-loss must be below entry.")
            if take_profit <= entry_price:
                raise ValueError("LONG take-profit must be above entry.")
        else:
            if stop_loss <= entry_price:
                raise ValueError("SHORT stop-loss must be above entry.")
            if take_profit >= entry_price:
                raise ValueError("SHORT take-profit must be below entry.")

        # --- Apply slippage to get effective fill price ---
        # LONG: buying, adverse slippage pushes fill price up.
        # SHORT: selling, adverse slippage pushes fill price down.
        if side == "LONG":
            effective_entry = entry_price * (1 + slippage_rate)
        else:
            effective_entry = entry_price * (1 - slippage_rate)
        effective_entry = round_price(effective_entry)

        # --- Load wallet & calculate position size (based on effective_entry) ---
        wallet = self.wallet_manager.load_wallet()
        sizing = self.risk_manager.calculate_position_size(
            balance=wallet.balance,
            free_margin=wallet.free_margin,
            risk_percent=risk_percent,
            entry_price=effective_entry,
            stop_loss=stop_loss,
            leverage=leverage,
            fee_rate=FEE_RATE,
            slippage_rate=0,  # already applied above; avoid double-counting
            side=side,
        )
        quantity = sizing["quantity"]
        if quantity <= 0:
            raise MarginException("Calculated quantity is zero or negative – insufficient funds or risk too small.")

        margin_required = sizing["margin_required"]

        # --- Calculate opening fee (based on effective notional value) ---
        notional_value = effective_entry * quantity
        fee_open = notional_value * FEE_RATE

        # Final sanity: wallet must cover margin + fee
        if wallet.balance < margin_required + fee_open:
            raise MarginException("Balance too low to cover margin and opening fee.")

        # --- Calculate liquidation price (based on effective_entry) ---
        # Simplified: price where unrealised loss = 100% of margin (maintenance margin = 0).
        if side == "LONG":
            liquidation_price = effective_entry - (margin_required / quantity)
        else:
            liquidation_price = effective_entry + (margin_required / quantity)
        liquidation_price = round_price(liquidation_price)

        # --- Construct position ---
        position = Position(
            symbol=symbol,
            side=side,
            entry_price=effective_entry,
            quantity=quantity,
            leverage=leverage,
            margin=margin_required,
            risk_percent=risk_percent,
            stop_loss=stop_loss,
            take_profit=take_profit,
            fee_open=fee_open,
            liquidation_price=liquidation_price,
            status="OPEN",
            metadata={},
        )

        # --- Update wallet ---
        wallet.balance -= fee_open
        wallet.total_fees += fee_open
        wallet.used_margin += margin_required
        wallet.open_positions.append(position)
        self._recalc_equity(wallet)
        wallet.peak_balance = max(wallet.peak_balance, wallet.equity)
        self.wallet_manager.save_wallet(wallet)

        # --- Log event ---
        self.logger.log_event(
            event="OPEN",
            position_id=position.id,
            symbol=symbol,
            side=side,
            price=effective_entry,
            quantity=quantity,
            fee=fee_open,
            pnl=0.0,
            balance=wallet.balance,
            equity=wallet.equity,
            reason="",
        )
        return position

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        reason: str,
        slippage_rate: float = DEFAULT_SLIPPAGE,
    ) -> Position:
        """
        Close an existing position, realise PnL, and update wallet.
        Uses the global FEE_RATE for closing fee (same rate as open_position).
        """
        wallet = self.wallet_manager.load_wallet()

        pos = None
        for p in wallet.open_positions:
            if p.id == position_id:
                pos = p
                break
        if pos is None:
            raise PositionException(f"Position {position_id} not found or already closed.")

        if pos.side == "LONG":
            effective_exit = exit_price * (1 - slippage_rate)
        else:
            effective_exit = exit_price * (1 + slippage_rate)
        effective_exit = round_price(effective_exit)

        if pos.side == "LONG":
            gross_pnl = (effective_exit - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - effective_exit) * pos.quantity

        fee_close = pos.quantity * effective_exit * FEE_RATE
        realized_pnl = gross_pnl - pos.fee_open - fee_close

        pos.exit_price = effective_exit
        pos.fee_close = fee_close
        pos.realized_pnl = realized_pnl
        pos.unrealized_pnl = 0.0
        pos.status = "LIQUIDATED" if reason == "LIQUIDATION" else "CLOSED"
        pos.closed_at = utc_now()

        wallet.balance += gross_pnl - fee_close
        wallet.total_fees += fee_close
        wallet.used_margin -= pos.margin
        wallet.realized_pnl += realized_pnl
        wallet.number_of_trades += 1
        if realized_pnl > 0:
            wallet.winning_trades += 1
        else:
            wallet.losing_trades += 1

        wallet.open_positions.remove(pos)
        wallet.closed_positions.append(pos)

        self._recalc_equity(wallet)
        if wallet.equity < wallet.peak_balance:
            drawdown = (wallet.peak_balance - wallet.equity) / wallet.peak_balance
            if drawdown > wallet.max_drawdown:
                wallet.max_drawdown = drawdown
        wallet.peak_balance = max(wallet.peak_balance, wallet.equity)

        self.wallet_manager.save_wallet(wallet)

        self.logger.log_event(
            event=reason,
            position_id=pos.id,
            symbol=pos.symbol,
            side=pos.side,
            price=effective_exit,
            quantity=pos.quantity,
            fee=fee_close,
            pnl=realized_pnl,
            balance=wallet.balance,
            equity=wallet.equity,
            reason=reason,
        )
        return pos

    def update_positions(self, current_price: float) -> None:
        """
        Check all open positions against stop‑loss, take‑profit,
        and liquidation triggers. Automatically closes any that are hit.

        Parameters
        ----------
        current_price : float
            Current market price of the instrument.
        """
        wallet = self.wallet_manager.load_wallet()
        # Snapshot IDs to avoid list mutation during iteration
        ids_to_close = []
        for pos in wallet.open_positions:
            if pos.side == "LONG":
                if current_price <= pos.liquidation_price:
                    ids_to_close.append((pos.id, "LIQUIDATION", pos.liquidation_price))
                elif current_price <= pos.stop_loss:
                    ids_to_close.append((pos.id, "STOP_LOSS", pos.stop_loss))
                elif current_price >= pos.take_profit:
                    ids_to_close.append((pos.id, "TAKE_PROFIT", pos.take_profit))
            else:  # SHORT
                if current_price >= pos.liquidation_price:
                    ids_to_close.append((pos.id, "LIQUIDATION", pos.liquidation_price))
                elif current_price >= pos.stop_loss:
                    ids_to_close.append((pos.id, "STOP_LOSS", pos.stop_loss))
                elif current_price <= pos.take_profit:
                    ids_to_close.append((pos.id, "TAKE_PROFIT", pos.take_profit))

        for pos_id, reason, trigger_price in ids_to_close:
            self.close_position(pos_id, trigger_price, reason)

        # After all closes, recalc unrealised PnL for the remaining positions
        wallet = self.wallet_manager.load_wallet()
        self._update_unrealized_pnl(wallet, current_price)
        self.wallet_manager.save_wallet(wallet)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _update_unrealized_pnl(self, wallet: Wallet, current_price: float) -> None:
        """Recalculate unrealised PnL for every open position and adjust equity."""
        total_unrealized = 0.0
        for pos in wallet.open_positions:
            if pos.side == "LONG":
                pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
            else:
                pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity
            total_unrealized += pos.unrealized_pnl
        wallet.unrealized_pnl = total_unrealized
        self._recalc_equity(wallet)

    def _recalc_equity(self, wallet: Wallet) -> None:
        """Update equity and free margin based on current state."""
        wallet.equity = wallet.balance + wallet.unrealized_pnl
        wallet.free_margin = wallet.equity - wallet.used_margin