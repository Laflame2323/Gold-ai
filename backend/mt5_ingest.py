"""Authenticated, read-only MetaTrader 5 candle ingestion."""
from __future__ import annotations

import re
import hashlib
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
    candles: list[MT5Candle] = Field(min_length=1, max_length=5000)

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
    """Archive larger historical batches in bounded, retry-safe Supabase writes."""
    rows = normalise_mt5_batch(batch)
    chunk_size = 500
    rows_saved = 0
    chunks_saved = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        result = _archive_reference_rows(
            "market_candles", chunk, "symbol,timeframe,candle_time,source"
        )
        if result.get("status") != "saved":
            return {
                "status": "error",
                "rows_sent": rows_saved,
                "chunks_saved": chunks_saved,
                "message": result.get("message", "A candle archive batch failed."),
            }
        rows_saved += result.get("rows_sent", len(chunk))
        chunks_saved += 1
    return {
        "status": "saved",
        "rows_sent": rows_saved,
        "chunks_saved": chunks_saved,
    }


class MT5Tick(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    time_msc: int = Field(gt=0)
    bid: float | None = Field(default=None, gt=0)
    ask: float | None = Field(default=None, gt=0)
    last: float | None = Field(default=None, gt=0)
    volume: float | None = Field(default=None, ge=0)
    volume_real: float | None = Field(default=None, ge=0)
    flags: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_tick(self):
        if self.bid is None and self.ask is None and self.last is None:
            raise ValueError("A tick must contain at least one price.")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("Tick ask cannot be below bid.")
        return self


class MT5TickBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker_server: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=32)
    server_utc_offset_seconds: int = Field(ge=-50400, le=50400)
    ticks: list[MT5Tick] = Field(min_length=1, max_length=500)

    @field_validator("broker_server", "symbol")
    @classmethod
    def validate_tick_labels(cls, value):
        value = value.strip()
        if not value or not re.fullmatch(r"[A-Za-z0-9._# -]+", value):
            raise ValueError("Invalid broker or symbol label.")
        return value


def archive_mt5_tick_batch(batch: MT5TickBatch) -> dict:
    """Store broker ticks in the isolated research-only tick archive."""
    now = datetime.now(timezone.utc)
    now_msc = int(now.timestamp() * 1000)
    received_at = now.isoformat()
    source = f"MT5:{batch.broker_server}"
    rows = []
    for tick in batch.ticks:
        utc_msc = tick.time_msc - batch.server_utc_offset_seconds * 1000
        if utc_msc > now_msc + 5000:
            raise ValueError("Future-dated MT5 ticks are not accepted.")
        if utc_msc <= 0:
            raise ValueError("Invalid MT5 tick timestamp.")
        key_payload = "|".join([
            str(utc_msc),
            "" if tick.bid is None else format(tick.bid, ".12g"),
            "" if tick.ask is None else format(tick.ask, ".12g"),
            "" if tick.last is None else format(tick.last, ".12g"),
            str(tick.flags),
        ])
        tick_key = hashlib.sha256(key_payload.encode("utf-8")).hexdigest()
        rows.append({
            "symbol": batch.symbol,
            "source": source,
            "tick_time_msc": utc_msc,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "volume_real": tick.volume_real,
            "flags": tick.flags,
            "tick_key": tick_key,
            "received_at": received_at,
        })
    result = _archive_reference_rows(
        "mt5_ticks_research", rows, "symbol,source,tick_key"
    )
    return result
