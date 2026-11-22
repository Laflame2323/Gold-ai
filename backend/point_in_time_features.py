"""Point-in-time alignment helpers for multi-timeframe Gold AI research.

All candle timestamps are Unix seconds marking BAR OPEN. A candle becomes
available only at open_time + timeframe_seconds. Decisions occur after the
lower-timeframe candle closes; an HTF candle is usable only after its close.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Any, Mapping, Sequence


def _timestamps(candles: Sequence[Mapping[str, Any]], name: str) -> list[int]:
    values: list[int] = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping) or "time" not in candle:
            raise ValueError(f"{name}[{index}] must contain a time field.")
        value = candle["time"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}[{index}].time must be numeric Unix seconds.")
        if int(value) != value:
            raise ValueError(f"{name}[{index}].time must be whole Unix seconds.")
        values.append(int(value))
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError(f"{name} timestamps must be strictly increasing.")
    return values


def align_completed_higher_timeframe(
    lower_candles: Sequence[Mapping[str, Any]],
    higher_candles: Sequence[Mapping[str, Any]],
    lower_timeframe_seconds: int,
    higher_timeframe_seconds: int,
) -> list[Mapping[str, Any] | None]:
    """Map each lower-timeframe decision to the latest fully completed HTF bar.

    Candle time fields represent bar-open times. For a lower bar opened at
    t, its decision time is t + lower_timeframe_seconds. An HTF bar opened
    at h is available at h + higher_timeframe_seconds. The helper never
    returns an HTF candle whose close is later than the decision.

    Returns one higher-timeframe candle (or None during warm-up) per lower
    bar. It does not resample data or infer broker session boundaries;
    callers must supply correctly session-aligned HTF candles.
    """
    for name, value in (
        ("lower_timeframe_seconds", lower_timeframe_seconds),
        ("higher_timeframe_seconds", higher_timeframe_seconds),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")

    lower_times = _timestamps(lower_candles, "lower_candles")
    higher_times = _timestamps(higher_candles, "higher_candles")
    higher_close_times = [stamp + higher_timeframe_seconds for stamp in higher_times]

    aligned: list[Mapping[str, Any] | None] = []
    for lower_open in lower_times:
        decision_time = lower_open + lower_timeframe_seconds
        completed_index = bisect_right(higher_close_times, decision_time) - 1
        aligned.append(higher_candles[completed_index] if completed_index >= 0 else None)
    return aligned
