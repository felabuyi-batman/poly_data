"""Position sizing helpers (no polars dependency)."""
from __future__ import annotations

from bot.config import KELLY_MAX_FRACTION


def kelly_size(p_win: float, market_price: float, bankroll: float,
               max_fraction: float = KELLY_MAX_FRACTION) -> float:
    if not (0 < market_price < 1):
        return 0.0
    b = (1 / market_price) - 1
    q = 1 - p_win
    f_star = (p_win * b - q) / b
    if f_star <= 0:
        return 0.0
    return round(bankroll * min(f_star, max_fraction), 2)
