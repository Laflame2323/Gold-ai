"""Symmetric, research-only trade protection for long and short XAUUSD positions.

This module proposes stop updates; it never sends orders or connects to a broker.
Call once per completed candle and persist best_price/stop_price per position.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Side = Literal["BUY", "SELL"]

# Starting research parameters, not optimised/live settings.
TIMEFRAME_PROFILES = {
    "M1": {"activation_atr": 0.8, "trail_atr": 1.2, "lock_fraction": 0.35},
    "M5": {"activation_atr": 0.8, "trail_atr": 1.3, "lock_fraction": 0.35},
    "M15": {"activation_atr": 0.9, "trail_atr": 1.4, "lock_fraction": 0.35},
    "M30": {"activation_atr": 1.0, "trail_atr": 1.5, "lock_fraction": 0.40},
    "H1": {"activation_atr": 1.0, "trail_atr": 1.7, "lock_fraction": 0.40},
    "H4": {"activation_atr": 1.1, "trail_atr": 2.0, "lock_fraction": 0.45},
    "D1": {"activation_atr": 1.2, "trail_atr": 2.4, "lock_fraction": 0.50},
}

@dataclass(frozen=True)
class ProtectionDecision:
    side: Side
    timeframe: str
    best_price: float
    proposed_stop: float
    stop_changed: bool
    should_close: bool
    close_reason: str | None
    profit_protection_active: bool

def manage_open_trade(*, side: Side, timeframe: str, entry_price: float,
                      current_price: float, best_price: float, current_stop: float,
                      atr: float, confirmed_reversal: bool = False,
                      profile: dict[str, float] | None = None) -> ProtectionDecision:
    """Calculate a monotonic trailing stop for BUY or SELL.

    best_price is the highest price since BUY entry or lowest since SELL entry.
    Update it from completed-candle highs/lows. confirmed_reversal must come
    from a separately validated signal rule, not a single adverse tick.
    """
    side, timeframe = side.upper(), timeframe.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if timeframe not in TIMEFRAME_PROFILES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    values = profile or TIMEFRAME_PROFILES[timeframe]
    activation = float(values["activation_atr"]) * atr
    trail = float(values["trail_atr"]) * atr
    lock_fraction = float(values["lock_fraction"])
    if min(entry_price, current_price, best_price) <= 0:
        raise ValueError("prices must be positive")
    if atr <= 0 or trail <= 0 or activation < 0:
        raise ValueError("ATR and stop distances must be positive")
    if not 0 <= lock_fraction <= 1:
        raise ValueError("lock_fraction must be between 0 and 1")

    if side == "BUY":
        best_price = max(best_price, current_price)
        favourable_move = best_price - entry_price
        active = favourable_move >= activation
        candidate = best_price - trail
        if active:
            candidate = max(candidate, entry_price + favourable_move * lock_fraction)
            proposed = max(current_stop, candidate)
        else:
            proposed = current_stop
        hit_stop = current_price <= proposed
    else:
        best_price = min(best_price, current_price)
        favourable_move = entry_price - best_price
        active = favourable_move >= activation
        candidate = best_price + trail
        if active:
            candidate = min(candidate, entry_price - favourable_move * lock_fraction)
            proposed = min(current_stop, candidate)
        else:
            proposed = current_stop
        hit_stop = current_price >= proposed

    reason = "trailing_stop_hit" if hit_stop else None
    if confirmed_reversal:
        reason = "confirmed_reversal"
    return ProtectionDecision(
        side=side, timeframe=timeframe, best_price=best_price,
        proposed_stop=proposed, stop_changed=proposed != current_stop,
        should_close=reason is not None, close_reason=reason,
        profit_protection_active=active,
    )
