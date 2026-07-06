"""Custom exception hierarchy for the trading engine."""

class TradingException(Exception):
    """Base exception for all trading errors."""

class WalletException(TradingException):
    """Raised when wallet operations fail."""

class RiskException(TradingException):
    """Raised for invalid risk parameters or calculations."""

class PositionException(TradingException):
    """Raised for errors related to position management."""

class MarginException(TradingException):
    """Raised when margin requirements are not met."""