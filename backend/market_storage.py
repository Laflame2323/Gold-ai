"""Persist reference-market candles and collection-run diagnostics in Supabase."""
from __future__ import annotations

import json
import logging
import os
import hashlib
import threading
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _supabase_credentials():
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    api_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    return base_url, api_key

# Avoid repeatedly upserting an unchanged closed-candle window on dashboard polls.
# Update the signature only after Supabase confirms a successful write.
_candle_archive_cache = {}
_candle_archive_lock = threading.Lock()


def _candle_window_signature(candles, data_status=None):
    fields = ("time", "open", "high", "low", "close", "volume")
    stable_rows = [{field: candle.get(field) for field in fields} for candle in candles]
    stable_payload = {"candles": stable_rows, "data_status": data_status}
    encoded = json.dumps(stable_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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

    cache_key = (base_url, symbol, timeframe, source)
    signature = _candle_window_signature(candles, data_status)
    with _candle_archive_lock:
        if _candle_archive_cache.get(cache_key) == signature:
            return {
                "status": "saved",
                "rows_sent": 0,
                "deduplicated": True,
                "http_status": 200,
            }

    query = urlencode({"on_conflict": "symbol,timeframe,candle_time,source"})
    request = Request(
        f"{base_url}/rest/v1/market_candles?{query}",
        data=json.dumps(rows, allow_nan=False).encode("utf-8"),
        headers={"apikey": api_key, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            with _candle_archive_lock:
                _candle_archive_cache[cache_key] = signature
            return {"status": "saved", "rows_sent": len(rows), "http_status": response.status}
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        logging.error("CANDLE_ARCHIVE HTTP %s: %s", exc.code, detail)
        return {"status": "error", "rows_sent": len(rows), "http_status": exc.code, "message": detail}
    except (URLError, TimeoutError, OSError) as exc:
        logging.exception("CANDLE_ARCHIVE network failure")
        return {"status": "error", "rows_sent": len(rows), "message": str(exc)[:300]}



def _archive_reference_rows(table, rows, conflict_columns):
    base_url, api_key = _supabase_credentials()
    if not base_url or not api_key:
        return {"status": "not_configured", "rows_sent": 0}
    if not rows:
        return {"status": "no_valid_rows", "rows_sent": 0}
    query = urlencode({"on_conflict": conflict_columns})
    request = Request(
        f"{base_url}/rest/v1/{table}?{query}",
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
            return {"status": "saved", "rows_sent": len(rows), "http_status": response.status}
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        logging.error("REFERENCE_ARCHIVE %s HTTP %s: %s", table, exc.code, detail[:800])
        return {"status": "error", "rows_sent": len(rows), "http_status": exc.code, "message": detail[:800]}
    except (URLError, TimeoutError, OSError) as exc:
        logging.warning("REFERENCE_ARCHIVE %s network failure: %s", table, str(exc)[:250])
        return {"status": "error", "rows_sent": len(rows), "message": str(exc)[:250]}


def archive_daily_history(history: dict) -> dict:
    fetched_at = datetime.now(timezone.utc).isoformat()
    data_state = history.get("data_state") or {}
    rows = []
    for point in history.get("points") or []:
        try:
            rows.append({
                "symbol": history.get("symbol", "XAUUSD"),
                "session_date": point["date"],
                "close": point["close"],
                "high": point.get("high"),
                "low": point.get("low"),
                "source": "XAUS daily history API",
                "fetched_at": fetched_at,
                "data_state": data_state.get("status"),
                "raw_metadata": {
                    "as_of": data_state.get("as_of"),
                    "source": data_state.get("source"),
                    "age_seconds": data_state.get("age_seconds"),
                    "high_52w": history.get("high_52w"),
                    "low_52w": history.get("low_52w"),
                    "return_1y_pct": history.get("return_1y_pct"),
                    "return_ytd_pct": history.get("return_ytd_pct"),
                },
            })
        except (KeyError, TypeError, ValueError):
            continue
    return _archive_reference_rows(
        "market_history_daily", rows, "symbol,session_date,source"
    )


def archive_intraday_prices(history: dict) -> dict:
    fetched_at = datetime.now(timezone.utc).isoformat()
    data_state = history.get("data_state") or {}
    rows = []
    for point in history.get("points") or []:
        try:
            rows.append({
                "symbol": history.get("symbol", "XAUUSD"),
                "observed_at": datetime.fromtimestamp(
                    int(point["time"]), timezone.utc
                ).isoformat(),
                "price": point["price"],
                "source": "XAUS intraday API",
                "fetched_at": fetched_at,
                "data_state": data_state.get("status"),
                "raw_metadata": {
                    "as_of": data_state.get("as_of"),
                    "source": data_state.get("source"),
                    "age_seconds": data_state.get("age_seconds"),
                    "coverage_seconds": history.get("coverage_seconds"),
                },
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return _archive_reference_rows(
        "market_intraday_prices", rows, "symbol,observed_at,source"
    )


def archive_gold_cot(cot_payload: dict) -> dict:
    """Upsert official weekly gold positioning snapshots into Supabase."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in cot_payload.get("history") or []:
        try:
            rows.append({
                "contract_code": item["contract_code"],
                "report_date": item["report_date"],
                "market_name": item.get("market_name"),
                "open_interest": item.get("open_interest"),
                "managed_money_long": item.get("managed_money_long"),
                "managed_money_short": item.get("managed_money_short"),
                "managed_money_spread": item.get("managed_money_spread"),
                "producer_merchant_long": item.get("producer_merchant_long"),
                "producer_merchant_short": item.get("producer_merchant_short"),
                "swap_dealer_long": item.get("swap_dealer_long"),
                "swap_dealer_short": item.get("swap_dealer_short"),
                "other_reportable_long": item.get("other_reportable_long"),
                "other_reportable_short": item.get("other_reportable_short"),
                "source": item.get("source") or "CFTC Disaggregated Futures Only",
                "fetched_at": fetched_at,
                "raw_metadata": {
                    "managed_money_net": item.get("managed_money_net"),
                    "managed_money_net_pct_oi": item.get("managed_money_net_pct_oi"),
                    "managed_money_net_change": item.get("managed_money_net_change"),
                    "managed_money_net_percentile_3y": item.get("managed_money_net_percentile_3y"),
                    "producer_merchant_net": item.get("producer_merchant_net"),
                    "swap_dealer_net": item.get("swap_dealer_net"),
                    "other_reportable_net": item.get("other_reportable_net"),
                    "expected_release_date": item.get("expected_release_date"),
                    "source_dataset": cot_payload.get("source_dataset"),
                },
            })
        except (KeyError, TypeError, ValueError):
            continue
    return _archive_reference_rows(
        "cot_gold_positions", rows, "contract_code,report_date,source"
    )


def archive_macro_context(payload: dict) -> dict:
    """Upsert daily public macro observations without filling missing dates."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for series_id, observations in (payload.get("history") or {}).items():
        for item in observations:
            try:
                rows.append({
                    "series_id": series_id,
                    "observation_date": item["observation_date"],
                    "value": item["value"],
                    "source": "Federal Reserve Bank of St. Louis FRED",
                    "fetched_at": fetched_at,
                    "raw_metadata": {
                        "label": (payload.get("series") or {}).get(series_id, {}).get("label"),
                        "unit": (payload.get("series") or {}).get(series_id, {}).get("unit"),
                    },
                })
            except (KeyError, TypeError, ValueError):
                continue
    return _archive_reference_rows(
        "macro_observations", rows, "series_id,observation_date,source"
    )
