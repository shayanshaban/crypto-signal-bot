"""Global constants and configuration parameters."""

# --- Fee & Slippage ---
FEE_RATE: float = 0.001         # 0.04% per trade
DEFAULT_SLIPPAGE: float = 0.0005  # 0.05%

# --- Position Limits ---
DEFAULT_MIN_QUANTITY: float = 0.0001
DEFAULT_LEVERAGE: int = 1

# --- Precision ---
QUANTITY_PRECISION: int = 3       # decimal places
PRICE_PRECISION: int = 2