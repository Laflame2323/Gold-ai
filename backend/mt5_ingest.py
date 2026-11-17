"""Authenticated, read-only MetaTrader 5 candle ingestion."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from market_storage import _archive_reference_rows

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900,
    "M30": 1800, "H1": 3600, "H4": 14400,
}


class MT5Candle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    time: int = Field(gt=0)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    tick_volume: int = Field(default=0, ge=0)
    real_volume: int = Field(default=0, ge=0)
    spread_points: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self):
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Candle high is below one of its OHLC values.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle low is above one of its OHLC values.")
        return self


class MT5Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker_server: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str
    server_utc_offset_seconds: int = Field(ge=-50400, le=50400)
    candles: list[MT5Candle] = Field(min_length=1, max_length=500)

    @field_validator("broker_server", "symbol")
    @classmethod
    def validate_safe_labels(cls, value):
        value = value.strip()
        if not value or not re.fullmatch(r"[A-Za-z0-9._# -]+", value):
            raise ValueError("Use letters, numbers, spaces, dots, underscores, hyphens or #.")
        return value

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value):
        if value not in TIMEFRAME_SECONDS:
            raise ValueError("Unsupported MT5 timeframe.")
        return value

    @model_validator(mode="after")
    def validate_unique_times(self):
        times = [item.time for item in self.candles]
        if len(times) != len(set(times)):
            raise ValueError("Duplicate candle timestamps are not accepted.")
        return self


def normalise_mt5_batch(batch: MT5Batch, now: datetime | None = None) -> list[dict]:
    """Convert authenticated, completed MT5 candles to the common archive schema."""
    current = now or datetime.now(timezone.utc)
    now_seconds = int(current.timestamp())
    interval = TIMEFRAME_SECONDS[batch.timeframe]
    # Convert broker-server wall time to UTC before storage.
    offset_seconds = batch.server_utc_offset_seconds
    source = f"MT5:{batch.broker_server}"
    received_at = current.astimezone(timezone.utc).isoformat()
    rows = []
    for candle in sorted(batch.candles, key=lambda item: item.time):
        utc_timestamp = candle.time - offset_seconds
        if utc_timestamp + interval > now_seconds + 5:
            raise ValueError("Forming or future candles are not accepted.")
        rows.append({
            "symbol": batch.symbol,
            "timeframe": batch.timeframe,
            "candle_time": datetime.fromtimestamp(utc_timestamp, timezone.utc).isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.tick_volume,
            "source": source,
            "fetched_at": received_at,
            "is_closed": True,
            "quality_status": "verified",
            "raw_metadata": {
                "feed_type": "authenticated_mt5_read_only",
                "broker_server": batch.broker_server,
                "server_utc_offset_seconds": batch.server_utc_offset_seconds,
                "timestamp_basis": "UTC_converted_from_broker_server_time",
                "historical_dst_offset_reconstructed": False,
                "tick_volume": candle.tick_volume,
                "real_volume": candle.real_volume,
                "spread_points": candle.spread_points,
                "received_at": received_at,
            },
        })
    return rows


def archive_mt5_batch(batch: MT5Batch) -> dict:
    rows = normalise_mt5_batch(batch)
    return _archive_reference_rows(
        "market_candles", rows, "symbol,timeframe,candle_time,source"
    )
