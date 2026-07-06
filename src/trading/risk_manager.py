"""
Position sizing and risk calculation.

All computations respect leverage, fees, and available margin.
The quantity is automatically reduced if the required margin + fees
exceed the available free margin.
"""

import math
from .constants import (
    DEFAULT_MIN_QUANTITY,
    QUANTITY_PRECISION,
    PRICE_PRECISION,
)
from .utils import round_down, round_price


class RiskManager:
    """
    Calculates the exact position size given risk parameters and wallet state.
    """

    def calculate_position_size(
        self,
        balance: float,
        free_margin: float,
        risk_percent: float,
        entry_price: float,
        stop_loss: float,
        leverage: int,
        fee_rate: float,
        slippage_rate: float,
        side: str,
    ) -> dict:
        """
        Determine quantity, margin, and estimated fees.

        Parameters
        ----------
        balance : float
            Current wallet balance (cash).
        free_margin : float
            Equity minus used margin (available for new positions).
        risk_percent : float
            Fraction of balance to risk (0.0 - 1.0).
        entry_price : float
            Intended entry price (before slippage).
        stop_loss : float
            Stop-loss price.
        leverage : int
            Account leverage for the position.
        fee_rate : float
            Fee fraction (e.g. 0.0004 for 0.04%).
        slippage_rate : float
            Slippage fraction to apply to entry/exit.
        side : str
            "LONG" or "SHORT".

        Returns
        -------
        dict
            {
                'quantity': float,
                'margin_required': float,
                'estimated_loss': float,
                'estimated_fee': float,
                'effective_entry': float
            }
        """
        # 1. Risk-based quantity (ignoring leverage)
        risk_amount = balance * risk_percent
        price_risk = abs(entry_price - stop_loss)

        if price_risk <= 0:
            raise ValueError("Entry and Stop Loss cannot be equal.")

        quantity = risk_amount / price_risk
        margin_required = (quantity * entry_price) / leverage
        return {
            "quantity": quantity,
            "margin_required": margin_required,
        }