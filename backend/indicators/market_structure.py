"""Confirmed swing-point market structure for research-only analysis.

Only completed candles are supplied by the ingestion layer. This module describes
structure; it does not create trade entries or claim predictive accuracy.
"""
from __future__ import annotations

import math


def analyse_market_structure(candles, lookback=80, swing_window=2):
    """Return confirmed swing levels and simple HH/HL or LH/LL structure."""
    if not isinstance(candles, list) or len(candles) < (2 * swing_window + 5):
        return {
            "status": "insufficient_data",
            "trend": "UNCONFIRMED",
            "breakout": "NONE",
            "support": None,
            "resistance": None,
            "explanation": "More completed candles are required to confirm swing points.",
        }

    recent = candles[-lookback:]
    highs = [float(c["high"]) for c in recent]
    lows = [float(c["low"]) for c in recent]
    closes = [float(c["close"]) for c in recent]

    if not all(math.isfinite(v) for v in highs + lows + closes):
        return {
            "status": "invalid_data",
            "trend": "UNCONFIRMED",
            "breakout": "NONE",
            "support": None,
            "resistance": None,
            "explanation": "Candle prices contain invalid numeric values.",
        }

    pivot_highs = []
    pivot_lows = []
    # Exclude the newest swing_window candles: a pivot is only confirmed
    # after the candles to its right have closed.
    for i in range(swing_window, len(recent) - swing_window):
        left_h = highs[i - swing_window:i]
        right_h = highs[i + 1:i + swing_window + 1]
        left_l = lows[i - swing_window:i]
        right_l = lows[i + 1:i + swing_window + 1]
        if highs[i] > max(left_h) and highs[i] >= max(right_h):
            pivot_highs.append((i, highs[i]))
        if lows[i] < min(left_l) and lows[i] <= min(right_l):
            pivot_lows.append((i, lows[i]))

    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return {
            "status": "unconfirmed",
            "trend": "UNCONFIRMED",
            "breakout": "NONE",
            "support": round(pivot_lows[-1][1], 4) if pivot_lows else None,
            "resistance": round(pivot_highs[-1][1], 4) if pivot_highs else None,
            "explanation": "Not enough confirmed swing highs and lows to classify structure.",
        }

    previous_high, latest_high = pivot_highs[-2][1], pivot_highs[-1][1]
    previous_low, latest_low = pivot_lows[-2][1], pivot_lows[-1][1]

    higher_high = latest_high > previous_high
    higher_low = latest_low > previous_low
    lower_high = latest_high < previous_high
    lower_low = latest_low < previous_low

    if higher_high and higher_low:
        trend = "HIGHER_HIGHS_HIGHER_LOWS"
    elif lower_high and lower_low:
        trend = "LOWER_HIGHS_LOWER_LOWS"
    else:
        trend = "MIXED"

    last_close = closes[-1]
    resistance = latest_high
    support = latest_low
    breakout = "NONE"
    if last_close > resistance:
        breakout = "BULLISH_BREAK_OF_STRUCTURE"
    elif last_close < support:
        breakout = "BEARISH_BREAK_OF_STRUCTURE"

    return {
        "status": "ready",
        "trend": trend,
        "breakout": breakout,
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "last_close": round(last_close, 4),
        "confirmed_swing_highs": len(pivot_highs),
        "confirmed_swing_lows": len(pivot_lows),
        "explanation": (
            "Structure is descriptive only. A break of a swing level can fail; "
            "wait for retest and independent confirmation."
        ),
    }
