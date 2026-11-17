"""Persist reference-market candles in Supabase using a server-side secret key.

No database writes occur until SUPABASE_URL and SUPABASE_SECRET_KEY
(or the legacy SUPABASE_SERVICE_ROLE_KEY) are configured on the backend.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def archive_market_candles(market_data: dict) -> dict:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    api_key = (
        os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    )
    if not base_url or not api_key:
        return {"status": "not_configured", "rows_sent": 0}

    candles = market_data.get("candles") or []
    timeframe = market_data.get("timeframe")
    symbol = market_data.get("symbol", "XAUUSD")
    source = market_data.get("provider_source") or "XAUS chart API"
    fetched_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "data_status": market_data.get("data_status"),
        "age_seconds": market_data.get("age_seconds"),
        "provider_interval": market_data.get("provider_interval"),
        "provider_range": market_data.get("provider_range"),
        "provider_updated_at": market_data.get("provider_updated_at"),
        "provider_data_state": market_data.get("provider_data_state"),
        "provider_note": market_data.get("provider_note"),
        "feed_type": "reference_market_not_broker_execution",
    }

    rows = []
    for candle in candles:
        try:
            rows.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "candle_time": datetime.fromtimestamp(
                    int(candle["time"]), timezone.utc
                ).isoformat(),
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle.get("volume"),
                "source": source,
                "fetched_at": fetched_at,
                "is_closed": True,
                "quality_status": "unverified",
                "raw_metadata": metadata,
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

    if not rows:
        return {"status": "no_valid_rows", "rows_sent": 0}

    query = urlencode({"on_conflict": "symbol,timeframe,candle_time,source"})
    request = Request(
        f"{base_url}/rest/v1/market_candles?{query}",
        data=json.dumps(rows, allow_nan=False).encode("utf-8"),
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return {
                "status": "saved",
                "rows_sent": len(rows),
                "http_status": response.status,
            }
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        return {
            "status": "error",
            "rows_sent": len(rows),
            "http_status": exc.code,
            "message": detail,
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "status": "error",
            "rows_sent": len(rows),
            "message": str(exc)[:300],
        }
