"""Leakage-safe directional labels for Gold AI's H1 and M15 research.

Labels are gross-price first-passage outcomes, not trade recommendations.
Candle timestamps are UTC Unix seconds marking bar opens. Only completed
bars are used for decisions; entry is the next bar open. Session gaps and
missing bars invalidate an event rather than being silently bridged.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

TIMEFRAME_SECONDS = {"H1": 3600, "M15": 900}
HORIZON_BARS = {"H1": (1, 2, 4), "M15": (1, 2)}
LABELS = {-1: "SHORT", 0: "NEUTRAL", 1: "LONG"}


def _validate_candles(candles: Sequence[Mapping[str, Any]], timeframe: str):
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError("timeframe must be H1 or M15")
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise ValueError("candles must be a sequence")
    cleaned = []
    previous_time = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping):
            raise ValueError(f"candle {index} must be a mapping")
        try:
            stamp = candle["time"]
            if isinstance(stamp, bool) or int(stamp) != stamp:
                raise ValueError
            stamp = int(stamp)
            values = {key: float(candle[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"candle {index} has invalid timestamp or OHLC") from None
        if previous_time is not None and stamp <= previous_time:
            raise ValueError("candle timestamps must be strictly increasing")
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError(f"candle {index} prices must be finite and positive")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"candle {index} has invalid high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"candle {index} has invalid low")
        cleaned.append({"time": stamp, **values})
        previous_time = stamp
    return cleaned


def _wilder_atr(candles, period):
    """Return causal Wilder ATR values; ATR[t] uses bars 0..t only."""
    true_ranges = []
    previous_close = None
    for candle in candles:
        high, low, close = candle["high"], candle["low"], candle["close"]
        true_ranges.append(
            high - low if previous_close is None else
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        previous_close = close
    result = [None] * len(candles)
    if len(true_ranges) < period:
        return result
    current = sum(true_ranges[:period]) / period
    result[period - 1] = current
    for index in range(period, len(true_ranges)):
        current = ((period - 1) * current + true_ranges[index]) / period
        result[index] = current
    return result


def build_directional_labels(
    candles: Sequence[Mapping[str, Any]],
    timeframe: str,
    horizon_bars: int,
    atr_period: int = 14,
    barrier_atr: float = 1.0,
    neutral_atr: float = 0.10,
):
    """Build one directional first-passage label per eligible completed bar.

    +1 means the upper barrier was reached first (LONG); -1 means the lower
    barrier was reached first (SHORT); 0 means same-bar ambiguity or a timeout
    move inside the neutral band. OHLC cannot resolve within-bar ordering.

    Events spanning missing bars/session gaps are excluded. Costs are not
    deducted here: neutral_atr is a label dead-zone, not a cost estimate.
    """
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError("timeframe must be H1 or M15")
    if isinstance(horizon_bars, bool) or horizon_bars not in HORIZON_BARS[timeframe]:
        raise ValueError(f"unsupported {timeframe} horizon; allowed: {HORIZON_BARS[timeframe]}")
    if isinstance(atr_period, bool) or not isinstance(atr_period, int) or atr_period < 2:
        raise ValueError("atr_period must be an integer >= 2")
    for name, value in (("barrier_atr", barrier_atr), ("neutral_atr", neutral_atr)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")

    data = _validate_candles(candles, timeframe)
    interval = TIMEFRAME_SECONDS[timeframe]
    atr_values = _wilder_atr(data, atr_period)
    events = []
    excluded = {"warmup": 0, "missing_or_session_gap": 0, "invalid_atr": 0}
    ambiguous = timeouts = 0

    for decision_index in range(atr_period - 1, len(data) - horizon_bars):
        atr = atr_values[decision_index]
        if atr is None or not math.isfinite(atr) or atr <= 0:
            excluded["invalid_atr"] += 1
            continue
        decision_time = data[decision_index]["time"] + interval
        entry_index = decision_index + 1
        entry_time = data[entry_index]["time"]
        expected_entry = decision_time
        end_index = decision_index + horizon_bars
        if entry_time != expected_entry:
            excluded["missing_or_session_gap"] += 1
            continue
        expected_times = [entry_time + offset * interval for offset in range(horizon_bars)]
        if any(data[decision_index + 1 + offset]["time"] != expected
               for offset, expected in enumerate(expected_times)):
            excluded["missing_or_session_gap"] += 1
            continue

        entry = data[entry_index]["open"]
        distance = float(barrier_atr) * atr
        upper, lower = entry + distance, entry - distance
        label, end_hit_index, reason = 0, end_index, "timeout_neutral"
        for index in range(entry_index, end_index + 1):
            candle = data[index]
            hit_upper = candle["high"] >= upper
            hit_lower = candle["low"] <= lower
            if hit_upper and hit_lower:
                label, end_hit_index, reason = 0, index, "ambiguous_same_bar"
                ambiguous += 1
                break
            if hit_upper:
                label, end_hit_index, reason = 1, index, "upper_barrier_first"
                break
            if hit_lower:
                label, end_hit_index, reason = -1, index, "lower_barrier_first"
                break
        else:
            timeout_return = data[end_index]["close"] - entry
            if timeout_return > float(neutral_atr) * atr:
                label, reason = 1, "timeout_long"
            elif timeout_return < -float(neutral_atr) * atr:
                label, reason = -1, "timeout_short"
            timeouts += 1

        events.append({
            "timeframe": timeframe,
            "decision_index": decision_index,
            "decision_time": decision_time,
            "entry_index": entry_index,
            "entry_time": entry_time,
            "entry_price": entry,
            "atr": atr,
            "upper_barrier": upper,
            "lower_barrier": lower,
            "horizon_bars": horizon_bars,
            "label_end_index": end_hit_index,
            "label_end_time": data[end_hit_index]["time"] + interval,
            "label": label,
            "label_name": LABELS[label],
            "reason": reason,
            "gross_price_move_at_timeout": (
                data[end_index]["close"] - entry if reason.startswith("timeout") else None
            ),
        })

    counts = {name: sum(event["label"] == value for event in events)
              for value, name in ((1, "long"), (-1, "short"), (0, "neutral"))}
    return {
        "status": "complete" if events else "insufficient_data",
        "timeframe": timeframe,
        "horizon_bars": horizon_bars,
        "horizon_seconds": horizon_bars * interval,
        "atr_method": f"Wilder ATR({atr_period}) including decision candle",
        "barrier_distance_atr": float(barrier_atr),
        "timeout_neutral_band_atr": float(neutral_atr),
        "label_definition": {"1": "LONG: upper barrier first", "-1": "SHORT: lower barrier first",
                             "0": "NEUTRAL: timeout inside dead-zone or ambiguous same-bar touch"},
        "events": events,
        "event_count": len(events),
        "class_counts": counts,
        "ambiguous_same_bar_count": ambiguous,
        "timeout_count": timeouts,
        "excluded_counts": excluded,
        "limitations": [
            "OHLC-only labels; same-bar barrier ordering is unknowable and is neutral.",
            "Gross price labels; no spread, commission, slippage or swap is deducted.",
            "Events crossing missing bars or session gaps are excluded.",
            "These are research targets, not executable trade signals or calibrated probabilities.",
        ],
    }
