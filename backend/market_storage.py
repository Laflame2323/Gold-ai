"""Persist reference-market candles and collection-run diagnostics in Supabase."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _supabase_credentials():
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    api_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    return base_url, api_key


def record_collector_run(started_at: datetime, archive_results: dict, provider_errors: dict) -> dict:
    """Write one compact audit record; diagnostics must never break market analysis."""
    base_url, api_key = _supabase_credentials()
    if not base_url or not api_key:
        return {"status": "not_configured"}

    saved = [tf for tf, result in archive_results.items() if result.get("status") == "saved"]
    failed = {
        tf: result.get("status", "unknown")
        for tf, result in archive_results.items()
        if result.get("status") != "saved"
    }
    failed.update({tf: "provider_error" for tf in provider_errors})
    rows_received = sum(int(result.get("rows_sent", 0) or 0) for result in archive_results.values())
    finished_at = datetime.now(timezone.utc)
    row = {
        "source": "XAUS chart API",
        "symbol": "XAUUSD",
        "started_at": started_at.astimezone(timezone.utc).isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": "success" if len(saved) == 6 and not failed else ("partial" if saved else "failed"),
        "rows_received": rows_received,
        "rows_inserted": rows_received,
        "timeframes": sorted(saved),
        "error_message": json.dumps(failed, separators=(",", ":")) if failed else None,
        "metadata": {"saved_timeframes": sorted(saved), "failed_timeframes": failed, "provider_errors": provider_errors, "rows_inserted_field_is_rows_submitted": True},
    }
    request = Request(
        f"{base_url}/rest/v1/collector_runs",
        data=json.dumps(row, allow_nan=False).encode("utf-8"),
        headers={"apikey": api_key, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Prefer": "return=minimal"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            return {"status": "saved", "http_status": response.status}
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        logging.warning("COLLECTOR_RUN_AUDIT HTTP %s: %s", exc.code, detail[:800])
        return {"status": "error", "http_status": exc.code, "message": detail[:800]}
    except (URLError, TimeoutError, OSError) as exc:
        logging.warning("COLLECTOR_RUN_AUDIT network failure: %s", str(exc)[:250])
        return {"status": "error", "message": str(exc)[:250]}


def archive_market_candles(market_data: dict) -> dict:
    base_url, api_key = _supabase_credentials()
    if not base_url or not api_key:
        logging.warning("CANDLE_ARCHIVE not_configured: Supabase URL or secret key missing")
        return {"status": "not_configured", "rows_sent": 0}

    candles = market_data.get("candles") or []
    timeframe = market_data.get("timeframe")
    symbol = market_data.get("symbol", "XAUUSD")
    source = market_data.get("provider_source") or "XAUS chart API"
    fetched_at = datetime.now(timezone.utc).isoformat()
    data_status = market_data.get("data_status")
    quality_status = "stale" if data_status == "stale" else "unverified"
    metadata = {
        "data_status": data_status,
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
                "candle_time": datetime.fromtimestamp(int(candle["time"]), timezone.utc).isoformat(),
                "open": candle["open"], "high": candle["high"], "low": candle["low"],
                "close": candle["close"], "volume": candle.get("volume"),
                "source": source, "fetched_at": fetched_at, "is_closed": True,
                "quality_status": quality_status, "raw_metadata": metadata,
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

    if not rows:
        return {"status": "no_valid_rows", "rows_sent": 0}

    query = urlencode({"on_conflict": "symbol,timeframe,candle_time,source"})
    request = Request(
        f"{base_url}/rest/v1/market_candles?{query}",
        data=json.dumps(rows, allow_nan=False).encode("utf-8"),
        headers={"apikey": api_key, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return {"status": "saved", "rows_sent": len(rows), "http_status": response.status}
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        logging.error("CANDLE_ARCHIVE HTTP %s: %s", exc.code, detail)
        return {"status": "error", "rows_sent": len(rows), "http_status": exc.code, "message": detail}
    except (URLError, TimeoutError, OSError) as exc:
        logging.exception("CANDLE_ARCHIVE network failure")
        return {"status": "error", "rows_sent": len(rows), "message": str(exc)[:300]}
