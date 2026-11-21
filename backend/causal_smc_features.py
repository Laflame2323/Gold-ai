"""Causal Smart Money Concepts proxies for Gold AI research.

Every feature at index t uses candles at or before t only. This deliberately
avoids centered windows and future-candle confirmation used by some public
SMC examples. These are measurable price-action proxies, not claims about
institutional order flow.
"""
from __future__ import annotations

import math


FEATURE_NAMES = [
    "smc_bull_fvg_atr",
    "smc_bear_fvg_atr",
    "smc_bull_sweep",
    "smc_bear_sweep",
    "smc_close_to_prior_high_atr",
    "smc_close_to_prior_low_atr",
    "smc_bull_breakout",
    "smc_bear_breakout",
    "smc_bull_ob_break_atr",
    "smc_bear_ob_break_atr",
    "smc_body_to_range",
    "smc_upper_wick_to_range",
    "smc_lower_wick_to_range",
    "smc_tick_volume_ratio",
    "regime_cusum_up_strength",
    "regime_cusum_down_strength",
    "regime_cusum_up_trigger",
    "regime_cusum_down_trigger",
    "regime_volatility_ratio",
]


def _cusum_regime_features(candles, index: int) -> list[float]:
    """Return bounded, causal CUSUM change-point and volatility features.

    The CUSUM state is rebuilt from a trailing window so it is deterministic
    for a decision candle and never reads candles after index. Returns are
    standardised by volatility estimated only from earlier returns.
    """
    first = max(1, index - 60)
    returns = []
    for position in range(first, index + 1):
        previous_close = float(candles[position - 1]["close"])
        current_close = float(candles[position]["close"])
        if previous_close <= 0 or current_close <= 0:
            raise ValueError("Candle closes must be positive")
        returns.append(current_close / previous_close - 1.0)

    positive, negative = 0.0, 0.0
    allowance, threshold = 0.5, 5.0
    for offset, value in enumerate(returns):
        history = returns[max(0, offset - 20):offset]
        if len(history) >= 5:
            mean = sum(history) / len(history)
            variance = sum((item - mean) ** 2 for item in history) / len(history)
            scale = math.sqrt(variance)
        else:
            prior = returns[:offset]
            if len(prior) >= 2:
                mean = sum(prior) / len(prior)
                scale = math.sqrt(sum((item - mean) ** 2 for item in prior) / len(prior))
            else:
                scale = 0.0
        # A tiny floor prevents division by zero on flat-price histories.
        z_score = (value / max(scale, 1e-8))
        positive = max(0.0, positive + z_score - allowance)
        negative = max(0.0, negative - z_score - allowance)

    recent = returns[-10:]
    longer = returns[-50:]
    def realised_vol(values):
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return math.sqrt(sum((item - mean) ** 2 for item in values) / len(values))
    short_vol, long_vol = realised_vol(recent), realised_vol(longer)
    volatility_ratio = short_vol / max(long_vol, 1e-8) if long_vol > 0 else 1.0

    return [
        min(positive / threshold, 3.0),
        min(negative / threshold, 3.0),
        float(positive >= threshold),
        float(negative >= threshold),
        min(max(volatility_ratio, 0.0), 10.0),
    ]


def causal_smc_features(candles, index: int, atr: float) -> list[float]:
    """Return causal, ATR-normalised SMC-style features for a completed candle."""
    if index < 30 or index >= len(candles) or not math.isfinite(atr) or atr <= 0:
        raise ValueError("At least 31 completed candles and a positive ATR are required")

    current = candles[index]
    high = float(current["high"])
    low = float(current["low"])
    open_ = float(current["open"])
    close = float(current["close"])
    span = max(high - low, 1e-12)
    prior = candles[index - 20:index]
    prior_high = max(float(c["high"]) for c in prior)
    prior_low = min(float(c["low"]) for c in prior)

    # Three-candle imbalance becomes knowable only when candle t has closed.
    two_back = candles[index - 2]
    bull_gap = max(0.0, low - float(two_back["high"])) / atr
    bear_gap = max(0.0, float(two_back["low"]) - high) / atr

    # Sweep and breakout levels are calculated from earlier candles only.
    bull_sweep = float(low < prior_low and close > prior_low)
    bear_sweep = float(high > prior_high and close < prior_high)
    bull_breakout = float(close > prior_high)
    bear_breakout = float(close < prior_low)

    # Causal order-block proxy: latest opposing candle in the prior 10 bars
    # whose extreme is crossed by the current close.
    bull_ob = 0.0
    bear_ob = 0.0
    for candle in reversed(candles[max(0, index - 10):index]):
        candle_open = float(candle["open"])
        candle_close = float(candle["close"])
        if bull_ob == 0.0 and candle_close < candle_open and close > float(candle["high"]):
            bull_ob = (close - float(candle["high"])) / atr
        if bear_ob == 0.0 and candle_close > candle_open and close < float(candle["low"]):
            bear_ob = (float(candle["low"]) - close) / atr
        if bull_ob and bear_ob:
            break

    tick_volume = current.get("tick_volume", current.get("volume"))
    previous_volumes = [
        float(c.get("tick_volume", c.get("volume", 0.0)) or 0.0)
        for c in prior
    ]
    volume_ratio = 1.0
    if tick_volume is not None and previous_volumes:
        average = sum(previous_volumes) / len(previous_volumes)
        if average > 0:
            volume_ratio = float(tick_volume) / average

    return [
        bull_gap, bear_gap, bull_sweep, bear_sweep,
        (close - prior_high) / atr, (close - prior_low) / atr,
        bull_breakout, bear_breakout, bull_ob, bear_ob,
        abs(close - open_) / span,
        (high - max(open_, close)) / span,
        (min(open_, close) - low) / span,
        min(max(volume_ratio, 0.0), 10.0),
        *_cusum_regime_features(candles, index),
    ]
