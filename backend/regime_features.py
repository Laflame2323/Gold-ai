"""Causal, descriptive market-regime features for Gold AI research.

Input candle timestamps are not used here; rows must already be chronological.
Every output row uses only the candle at that index and earlier observations.
Regime tags are descriptive research labels, not trade instructions.
"""
from __future__ import annotations

import math


def _validate(candles):
    if not isinstance(candles, list):
        raise ValueError("candles must be a list")
    clean = []
    for index, candle in enumerate(candles):
        try:
            values = {key: float(candle[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"invalid candle at index {index}")
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError(f"invalid OHLC value at index {index}")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"invalid high at index {index}")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"invalid low at index {index}")
        clean.append(values)
    return clean


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for item in values[period:]:
        value += alpha * (item - value)
    return value


def _true_ranges(candles):
    result = []
    previous_close = None
    for row in candles:
        high, low, close = row["high"], row["low"], row["close"]
        result.append(high - low if previous_close is None else
                      max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    return result


def _wilder_atr(true_ranges, period):
    if len(true_ranges) < period:
        return None
    value = sum(true_ranges[:period]) / period
    for item in true_ranges[period:]:
        value = ((period - 1) * value + item) / period
    return value


def build_regime_features(candles, atr_period=14, trend_period=20,
                          slow_period=50, efficiency_period=20,
                          volatility_lookback=100):
    """Return causal feature rows with None during indicator warm-up.

    ATR percentile uses only the trailing ATR observations available at the
    current completed candle. Threshold-based regime tags are deliberately
    coarse descriptive buckets and must be validated before use in a policy.
    """
    for name, value in (("atr_period", atr_period), ("trend_period", trend_period),
                        ("slow_period", slow_period), ("efficiency_period", efficiency_period),
                        ("volatility_lookback", volatility_lookback)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(f"{name} must be an integer >= 2")
    if trend_period >= slow_period:
        raise ValueError("trend_period must be smaller than slow_period")

    rows = _validate(candles)
    closes = [row["close"] for row in rows]
    ranges = _true_ranges(rows)
    output = []
    atr_history = []

    for index, row in enumerate(rows):
        if index + 1 < max(slow_period, atr_period, efficiency_period + 1):
            output.append(None)
            continue

        window_closes = closes[:index + 1]
        atr = _wilder_atr(ranges[:index + 1], atr_period)
        if atr is None or atr <= 0:
            output.append(None)
            continue
        fast_ema = _ema(window_closes, trend_period)
        slow_ema = _ema(window_closes, slow_period)
        prior_fast_ema = _ema(window_closes[:-1], trend_period)
        if fast_ema is None or slow_ema is None or prior_fast_ema is None:
            output.append(None)
            continue

        path = window_closes[-efficiency_period - 1:]
        path_length = sum(abs(path[i] - path[i - 1]) for i in range(1, len(path)))
        efficiency = abs(path[-1] - path[0]) / path_length if path_length else 0.0
        slope_atr = (fast_ema - prior_fast_ema) / atr
        ema_spread_atr = (fast_ema - slow_ema) / atr
        recent = rows[max(0, index - 19):index + 1]
        recent_high = max(item["high"] for item in recent)
        recent_low = min(item["low"] for item in recent)
        range_position = ((row["close"] - recent_low) / (recent_high - recent_low)
                          if recent_high > recent_low else 0.5)
        returns = [window_closes[i] / window_closes[i - 1] - 1.0
                   for i in range(max(1, index - 9), index + 1)]
        realized_volatility = math.sqrt(sum(value * value for value in returns) / len(returns))

        atr_history.append(atr)
        percentile_window = atr_history[-volatility_lookback:]
        atr_percentile = sum(value <= atr for value in percentile_window) / len(percentile_window)

        trend_score = abs(ema_spread_atr)
        if trend_score >= 0.5 and efficiency >= 0.35:
            trend_regime = "directional"
        elif efficiency < 0.20:
            trend_regime = "choppy"
        else:
            trend_regime = "mixed"
        volatility_regime = ("high" if atr_percentile >= 0.80 else
                             "low" if atr_percentile <= 0.20 else "normal")

        output.append({
            "index": index,
            "atr": atr,
            "atr_pct_of_price": atr / row["close"],
            "atr_percentile": atr_percentile,
            "ema_spread_atr": ema_spread_atr,
            "ema_slope_atr": slope_atr,
            "efficiency_ratio": efficiency,
            "range_position_20": range_position,
            "realized_volatility_10": realized_volatility,
            "trend_regime": trend_regime,
            "volatility_regime": volatility_regime,
            "research_only": True,
        })

    return {
        "feature_names": [
            "atr_pct_of_price", "atr_percentile", "ema_spread_atr",
            "ema_slope_atr", "efficiency_ratio", "range_position_20",
            "realized_volatility_10",
        ],
        "rows": output,
        "row_count": sum(item is not None for item in output),
        "warmup_count": sum(item is None for item in output),
        "research_only": True,
    }
