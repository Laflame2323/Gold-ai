"""Deterministic candle integrity and gap audit for research datasets.

This module reports gaps; it deliberately does not assume a broker session calendar
or silently delete/fill candles. All timestamps are Unix seconds in UTC.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any


def _raw_fingerprint(candles: list[dict]) -> str:
    payload = json.dumps(candles, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_weekend_crossing(start_ts: int, end_ts: int) -> bool:
    start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    # Saturday=5, Sunday=6. Include a weekend boundary crossed between bars.
    day = start.date()
    while day <= end.date():
        if day.weekday() >= 5:
            boundary = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
            if start_ts < boundary <= end_ts or day == start.date() or day == end.date():
                return True
        from datetime import timedelta
        day += timedelta(days=1)
    return False


def audit_candles(candles: list[dict], *, timeframe_seconds: int,
                  label: str = "candles", unusual_gap_multiple: int = 3) -> dict[str, Any]:
    """Audit ordering, duplicates, OHLC geometry, and timestamp gaps.

    Gap classification is descriptive only: without a verified broker session
    calendar, a non-weekend gap is not automatically considered a data defect.
    """
    if not isinstance(candles, list) or not candles:
        raise ValueError(f"{label} must be a non-empty list")
    if isinstance(timeframe_seconds, bool) or not isinstance(timeframe_seconds, int) or timeframe_seconds <= 0:
        raise ValueError("timeframe_seconds must be a positive integer")
    if isinstance(unusual_gap_multiple, bool) or not isinstance(unusual_gap_multiple, int) or unusual_gap_multiple < 2:
        raise ValueError("unusual_gap_multiple must be an integer >= 2")

    fingerprint = _raw_fingerprint(candles)
    errors: list[dict] = []
    gaps: list[dict] = []
    seen: set[int] = set()
    previous_ts: int | None = None
    valid_rows = 0

    for i, row in enumerate(candles):
        if not isinstance(row, dict):
            errors.append({"index": i, "reason": "row_not_object"})
            continue
        raw_ts = row.get("time", row.get("timestamp"))
        try:
            if isinstance(raw_ts, bool):
                raise ValueError
            ts = int(raw_ts)
            if str(raw_ts).strip() not in (str(ts), f"{ts}.0") or ts <= 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            errors.append({"index": i, "reason": "invalid_unix_timestamp"})
            continue

        if ts in seen:
            errors.append({"index": i, "time": ts, "reason": "duplicate_timestamp"})
        if previous_ts is not None and ts < previous_ts:
            errors.append({"index": i, "time": ts, "previous_time": previous_ts,
                           "reason": "out_of_order_timestamp"})

        values = {}
        for key in ("open", "high", "low", "close"):
            try:
                value = float(row.get(key))
                if not math.isfinite(value) or value <= 0:
                    raise ValueError
                values[key] = value
            except (TypeError, ValueError, OverflowError):
                errors.append({"index": i, "time": ts, "reason": f"invalid_{key}"})
        if len(values) == 4:
            if values["high"] < max(values["open"], values["close"], values["low"]):
                errors.append({"index": i, "time": ts, "reason": "invalid_ohlc_high"})
            if values["low"] > min(values["open"], values["close"], values["high"]):
                errors.append({"index": i, "time": ts, "reason": "invalid_ohlc_low"})
            valid_rows += 1

        if previous_ts is not None and ts > previous_ts:
            delta = ts - previous_ts
            if delta > timeframe_seconds:
                multiple = delta / timeframe_seconds
                weekend = _is_weekend_crossing(previous_ts, ts)
                gaps.append({
                    "from_time": previous_ts,
                    "to_time": ts,
                    "elapsed_seconds": delta,
                    "expected_missing_bars": max(0, round(multiple) - 1) if delta % timeframe_seconds == 0 else None,
                    "interval_is_exact_multiple": delta % timeframe_seconds == 0,
                    "weekend_boundary_crossed": weekend,
                    "classification": "weekend_or_week_open_gap" if weekend else
                        "unusual_non_weekend_gap" if delta >= unusual_gap_multiple * timeframe_seconds else
                        "short_non_weekend_gap",
                    "review_required": True,
                })
        seen.add(ts)
        previous_ts = ts

    status = "invalid" if errors else "gaps_require_review" if gaps else "clean"
    return {
        "label": label,
        "status": status,
        "timeframe_seconds": timeframe_seconds,
        "input_rows": len(candles),
        "valid_ohlc_rows": valid_rows,
        "error_count": len(errors),
        "gap_count": len(gaps),
        "errors": errors,
        "gaps": gaps,
        "first_timestamp": candles[0].get("time", candles[0].get("timestamp")) if isinstance(candles[0], dict) else None,
        "last_timestamp": candles[-1].get("time", candles[-1].get("timestamp")) if isinstance(candles[-1], dict) else None,
        "dataset_payload_sha256": fingerprint,
        "execution_enabled": False,
        "policy": [
            "No missing candles are synthesized or silently removed.",
            "Weekend/session classification is descriptive, not a broker-calendar verdict.",
            "Every reported gap requires review before formal replay.",
            "The fingerprint hashes the exact supplied row payload and ordering.",
        ],
    }
