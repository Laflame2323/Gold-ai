"""Read-only XAU candle access for Gold AI.

XAUS chart candles are reference-market data, not a user's broker execution feed.
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://xaus.com/api/v1/chart"
CACHE_TTL_SECONDS = 60
TIMEFRAME_CONFIG = {
    "M1": ("1m", "1d", 60),
    "M5": ("5m", "5d", 300),
    "M15": ("15m", "5d", 900),
    "M30": ("30m", "1mo", 1800),
    "H1": ("1h", "3mo", 3600),
}

_cache = {}
_cache_lock = threading.Lock()


class MarketDataError(Exception):
    """Raised when the upstream market data cannot be trusted or parsed."""


def _timestamp_seconds(value):
    if isinstance(value, bool):
        raise ValueError("Invalid candle timestamp")
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 100_000_000_000:
            stamp /= 1000.0
        return int(stamp)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return _timestamp_seconds(int(text))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    raise ValueError("Invalid candle timestamp")


def _normalise_candles(raw_points):
    if not isinstance(raw_points, list):
        raise MarketDataError("The candle provider did not return a points list.")

    candles_by_time = {}
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        try:
            stamp = _timestamp_seconds(
                point.get("t", point.get("timestamp", point.get("time")))
            )
            candle = {
                "time": stamp,
                "open": float(point.get("o", point.get("open"))),
                "high": float(point.get("h", point.get("high"))),
                "low": float(point.get("l", point.get("low"))),
                "close": float(point.get("c", point.get("close"))),
                "volume": point.get("v", point.get("volume")),
            }
            values = [candle[k] for k in ("open", "high", "low", "close")]
            if not all(math.isfinite(value) for value in values):
                continue
            if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
                continue
            if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
                continue
            if candle["volume"] is not None:
                try:
                    candle["volume"] = float(candle["volume"])
                    if not math.isfinite(candle["volume"]):
                        candle["volume"] = None
                except (TypeError, ValueError):
                    candle["volume"] = None
            candles_by_time[stamp] = candle
        except (TypeError, ValueError, OverflowError):
            continue

    candles = [candles_by_time[key] for key in sorted(candles_by_time)]
    if not candles:
        raise MarketDataError("The candle provider returned no valid OHLC candles.")
    return candles


def _extract_points(payload):
    candidates = [payload.get("points"), payload.get("candles"), payload.get("data")]
    chart = payload.get("chart")
    if isinstance(chart, dict):
        candidates.extend([chart.get("points"), chart.get("candles"), chart.get("data")])
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    keys = ", ".join(sorted(payload.keys())) if isinstance(payload, dict) else "unknown"
    raise MarketDataError(
        f"Unexpected candle response format from XAUS (top-level keys: {keys})."
    )


def _fetch_provider_candles(interval, period):
    cache_key = (interval, period)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    query = urlencode({"symbol": "xau", "range": period, "interval": interval})
    request = Request(
        f"{BASE_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "GoldAI/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise MarketDataError(
                "XAUS rate limit reached. Please wait one minute and retry."
            ) from exc
        raise MarketDataError(f"XAUS candle service returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MarketDataError("Could not retrieve candle data from XAUS.") from exc

    if not isinstance(payload, dict):
        raise MarketDataError("XAUS returned an invalid candle response.")

    candles = _normalise_candles(_extract_points(payload))
    result = {
        "candles": candles,
        "provider_updated_at": payload.get("updated_at"),
        "provider_data_state": payload.get("data_state"),
        "provider_source": payload.get("source") or "XAUS chart API",
        "provider_note": payload.get("note"),
    }
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), result)
    return result


def _aggregate_h4(hourly_candles):
    """Build completed 4-hour candles; skip groups with missing H1 bars."""
    buckets = {}
    for candle in hourly_candles:
        bucket_start = (candle["time"] // 14_400) * 14_400
        buckets.setdefault(bucket_start, []).append(candle)

    result = []
    for bucket_start in sorted(buckets):
        group = sorted(buckets[bucket_start], key=lambda item: item["time"])
        expected_times = [bucket_start + hour * 3600 for hour in range(4)]
        if len(group) != 4 or [item["time"] for item in group] != expected_times:
            continue
        volumes = [item["volume"] for item in group]
        result.append({
            "time": bucket_start,
            "open": group[0]["open"],
            "high": max(item["high"] for item in group),
            "low": min(item["low"] for item in group),
            "close": group[-1]["close"],
            "volume": sum(volumes) if all(v is not None for v in volumes) else None,
        })

    if not result:
        raise MarketDataError("Not enough complete hourly candles to build H4 candles yet.")
    return result


def get_market_candles(timeframe):
    timeframe = timeframe.upper()
    if timeframe == "H4":
        hourly = _fetch_provider_candles(*TIMEFRAME_CONFIG["H1"][:2])
        candles = _aggregate_h4(hourly["candles"])
        interval_seconds = 14_400
        provider_interval = "derived from 1h"
        provider_range = "3mo"
        provider_updated_at = hourly["provider_updated_at"]
        provider_data_state = hourly["provider_data_state"]
        provider_source = hourly["provider_source"]
        provider_note = hourly["provider_note"]
    elif timeframe in TIMEFRAME_CONFIG:
        interval, period, interval_seconds = TIMEFRAME_CONFIG[timeframe]
        upstream = _fetch_provider_candles(interval, period)
        candles = upstream["candles"]
        provider_interval = interval
        provider_range = period
        provider_updated_at = upstream["provider_updated_at"]
        provider_data_state = upstream["provider_data_state"]
        provider_source = upstream["provider_source"]
        provider_note = upstream["provider_note"]
    else:
        raise MarketDataError("Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4.")

    last_candle = candles[-1]
    now = int(time.time())
    age_seconds = max(0, now - (last_candle["time"] + interval_seconds))
    # Keep short timeframes strict; longer timeframes get a proportionate window.
    # Stale candles must never be treated as current trading conditions.
    freshness_limit = max(180, int(interval_seconds * 2))
    status = "recent" if age_seconds <= freshness_limit else "stale"
    last_candle_at = datetime.fromtimestamp(
        last_candle["time"], timezone.utc
    ).isoformat()

    return {
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
        "last_candle_at": last_candle_at,
        "age_seconds": age_seconds,
        "data_status": status,
        "source": "XAUS chart API (reference market data)",
        "provider_source": provider_source,
        "provider_interval": provider_interval,
        "provider_range": provider_range,
        "provider_updated_at": provider_updated_at,
        "provider_data_state": provider_data_state,
        "provider_note": provider_note,
        "warning": (
            "Reference-market candles may differ from your MT5 broker's XAUUSD "
            "prices; verify before using signals for trading."
        ),
    }
