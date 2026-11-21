"""Leakage-safe multi-timeframe feature alignment for Gold AI research.

Candle timestamps are candle OPEN times. A feature may use a candle only when
its close time is at or before the base decision candle's close time.
This module builds features only; it does not train or persist a model.
"""
from __future__ import annotations

import math
from bisect import bisect_right


TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900,
    "M30": 1800, "H1": 3600, "H4": 14400,
}


def _validate_candles(candles, timeframe):
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if not isinstance(candles, list):
        raise ValueError(f"{timeframe} candles must be a list")
    previous = None
    clean = []
    for candle in candles:
        try:
            stamp = int(candle["time"])
            values = {key: float(candle[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"Invalid {timeframe} candle")
        if previous is not None and stamp <= previous:
            raise ValueError(f"{timeframe} candles must be strictly time ordered")
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError(f"{timeframe} OHLC values must be finite and positive")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"Inconsistent {timeframe} candle high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"Inconsistent {timeframe} candle low")
        previous = stamp
        clean.append({"time": stamp, **values})
    return clean


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for item in values[period:]:
        value += alpha * (item - value)
    return value


def _rsi(values, period=14):
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    if len(changes) < period:
        return 50.0
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    gain = sum(gains[:period]) / period
    loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        gain = ((period - 1) * gain + gains[i]) / period
        loss = ((period - 1) * loss + losses[i]) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _feature_names(timeframes):
    names = []
    for timeframe in timeframes:
        prefix = timeframe.lower()
        names.extend([
            f"{prefix}_return_1",
            f"{prefix}_return_3",
            f"{prefix}_return_5",
            f"{prefix}_ema_gap_10",
            f"{prefix}_ema_gap_30",
            f"{prefix}_rsi_14",
            f"{prefix}_range_pct",
            f"{prefix}_body_pct",
            f"{prefix}_volatility_10",
            f"{prefix}_ema10_slope_3_atr",
            f"{prefix}_ema30_slope_5_atr",
            f"{prefix}_distance_prior_high_20_atr",
            f"{prefix}_distance_prior_low_20_atr",
            f"{prefix}_close_location",
            f"{prefix}_upper_wick_ratio",
            f"{prefix}_lower_wick_ratio",
            f"{prefix}_range_to_atr",
        ])
    return names


def _features(candles, index):
    window = candles[max(0, index - 199):index + 1]
    if len(window) < 35:
        return None
    closes = [item["close"] for item in window]
    current = closes[-1]
    changes = [closes[i] / closes[i - 1] - 1.0
               for i in range(len(closes) - 10, len(closes))]
    row = window[-1]
    ema10 = _ema(closes, 10)
    ema30 = _ema(closes, 30)
    ema10_previous = _ema(closes[:-3], 10)
    ema30_previous = _ema(closes[:-5], 30)

    true_ranges = []
    for j in range(1, len(window)):
        candle = window[j]
        previous_close = closes[j - 1]
        true_ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close),
        ))
    atr = sum(true_ranges[-14:]) / min(14, len(true_ranges))
    atr = max(atr, 1e-12)

    prior = window[-21:-1]
    prior_high = max(item["high"] for item in prior)
    prior_low = min(item["low"] for item in prior)
    candle_range = max(row["high"] - row["low"], 1e-12)
    upper_wick = row["high"] - max(row["open"], row["close"])
    lower_wick = min(row["open"], row["close"]) - row["low"]

    values = [
        current / closes[-2] - 1.0,
        current / closes[-4] - 1.0,
        current / closes[-6] - 1.0,
        current / ema10 - 1.0,
        current / ema30 - 1.0,
        (_rsi(closes) - 50.0) / 50.0,
        (row["high"] - row["low"]) / current,
        (row["close"] - row["open"]) / current,
        math.sqrt(sum(change * change for change in changes) / len(changes)),
        (ema10 - ema10_previous) / (3.0 * atr),
        (ema30 - ema30_previous) / (5.0 * atr),
        (current - prior_high) / atr,
        (current - prior_low) / atr,
        min(max((row["close"] - row["low"]) / candle_range, 0.0), 1.0),
        min(max(upper_wick / candle_range, 0.0), 1.0),
        min(max(lower_wick / candle_range, 0.0), 1.0),
        candle_range / atr,
    ]
    if not all(math.isfinite(value) for value in values):
        return None
    return values


def build_multitimeframe_features(
    candles_by_timeframe,
    base_timeframe="H1",
    timeframes=("H4", "H1", "M30", "M15"),
):
    """Align completed timeframe candles to each completed base candle.

    All input timestamps are candle OPEN times (Unix seconds). For a base
    candle at t, its decision time is t + base interval. Source candles are
    eligible only when source_open + source_interval <= decision_time.
    """
    if base_timeframe not in TIMEFRAME_SECONDS:
        raise ValueError("Unsupported base timeframe")
    selected = tuple(dict.fromkeys(timeframes))
    if not selected or base_timeframe not in selected:
        raise ValueError("timeframes must include the base timeframe")
    for timeframe in selected:
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if timeframe not in candles_by_timeframe:
            raise ValueError(f"Missing {timeframe} candle history")

    cleaned = {
        timeframe: _validate_candles(candles_by_timeframe[timeframe], timeframe)
        for timeframe in selected
    }
    close_times = {
        timeframe: [candle["time"] + TIMEFRAME_SECONDS[timeframe]
                    for candle in candles]
        for timeframe, candles in cleaned.items()
    }
    names = _feature_names(selected)
    rows = []
    feature_cache = {timeframe: {} for timeframe in selected}
    base_interval = TIMEFRAME_SECONDS[base_timeframe]

    for base_index, base_candle in enumerate(cleaned[base_timeframe]):
        decision_time = base_candle["time"] + base_interval
        feature_values = []
        source_times = {}
        ready = True
        for timeframe in selected:
            source_index = bisect_right(close_times[timeframe], decision_time) - 1
            if source_index < 30:
                ready = False
                break
            source_close_time = close_times[timeframe][source_index]
            if decision_time - source_close_time >= TIMEFRAME_SECONDS[timeframe]:
                ready = False
                break
            cache = feature_cache[timeframe]
            if source_index not in cache:
                cache[source_index] = _features(cleaned[timeframe], source_index)
            values = cache[source_index]
            if values is None:
                ready = False
                break
            feature_values.extend(values)
            source_times[timeframe] = cleaned[timeframe][source_index]["time"]
        if ready:
            rows.append({
                "decision_time": decision_time,
                "features": feature_values,
                "source_candle_times": source_times,
            })

    return {
        "base_timeframe": base_timeframe,
        "timeframes": list(selected),
        "feature_names": names,
        "rows": rows,
        "row_count": len(rows),
        "alignment_rule": "source candle close time must be <= base decision candle close time",
        "research_only": True,
    }
