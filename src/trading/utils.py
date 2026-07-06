"""Utility functions: ID generation, timestamps, rounding, JSON helpers."""

import uuid
import math
from datetime import datetime, timezone


def generate_id() -> str:
    """Generate a unique position ID."""
    return uuid.uuid4().hex[:12]


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def round_down(value: float, decimals: int) -> float:
    """Round down to a given number of decimal places (floor)."""
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def round_price(value: float, decimals: int = 2) -> float:
    """Standard rounding for prices."""
    return round(value, decimals)