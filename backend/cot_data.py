"""Official CFTC gold positioning data (weekly, delayed, read-only)."""
from __future__ import annotations
import json, math, threading, time
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CFTC_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
GOLD_CONTRACT_CODE = "088691"
COT_CACHE_SECONDS = 6 * 60 * 60
_cache = {"at": 0.0, "payload": None}
_lock = threading.Lock()


class COTDataError(Exception):
    """Raised when the official CFTC report cannot be trusted or retrieved."""


def _optional_int(value):
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError("Invalid CFTC position value")
    return int(number)


def normalise_cot_rows(raw_rows):
    if not isinstance(raw_rows, list):
        raise COTDataError("CFTC returned an unexpected report format.")
    fields = {
        "open_interest": "open_interest_all",
        "managed_money_long": "m_money_positions_long_all",
        "managed_money_short": "m_money_positions_short_all",
        "managed_money_spread": "m_money_positions_spread_all",
        "producer_merchant_long": "prod_merc_positions_long",
        "producer_merchant_short": "prod_merc_positions_short",
        "swap_dealer_long": "swap_positions_long_all",
        "swap_dealer_short": "swap__positions_short_all",
        "other_reportable_long": "other_rept_positions_long",
        "other_reportable_short": "other_rept_positions_short",
    }
    by_date = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        try:
            report_date = date.fromisoformat(str(raw["report_date_as_yyyy_mm_dd"])[:10])
            record = {
                "contract_code": GOLD_CONTRACT_CODE,
                "report_date": report_date.isoformat(),
                "market_name": str(raw.get("market_and_exchange_names") or "GOLD"),
            }
            for target, source in fields.items():
                record[target] = _optional_int(raw.get(source))
            if record["open_interest"] is None or record["open_interest"] <= 0:
                continue
            if record["managed_money_long"] is None or record["managed_money_short"] is None:
                continue
            record["managed_money_net"] = record["managed_money_long"] - record["managed_money_short"]
            record["managed_money_net_pct_oi"] = record["managed_money_net"] / record["open_interest"] * 100
            # Tuesday positions are normally published Friday; holiday delays can occur.
            record["expected_release_date"] = (report_date + timedelta(days=3)).isoformat()
            record["source"] = "CFTC Disaggregated Futures Only (72hh-3qpy)"
            by_date[record["report_date"]] = record
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    records = [by_date[key] for key in sorted(by_date)]
    if not records:
        raise COTDataError("CFTC returned no valid gold positioning records.")
    for index, record in enumerate(records):
        previous = records[index - 1] if index else None
        record["managed_money_net_change"] = (
            record["managed_money_net"] - previous["managed_money_net"] if previous else None
        )
    recent = [item["managed_money_net"] for item in records[-156:]]
    latest = records[-1]["managed_money_net"]
    records[-1]["managed_money_net_percentile_3y"] = round(
        100 * sum(value <= latest for value in recent) / len(recent), 1
    )
    return records


def get_gold_cot(force_refresh=False):
    now = time.monotonic()
    with _lock:
        if not force_refresh and _cache["payload"] is not None and now - _cache["at"] < COT_CACHE_SECONDS:
            return _cache["payload"]
    select = ",".join([
        "report_date_as_yyyy_mm_dd", "market_and_exchange_names", "open_interest_all",
        "m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread_all",
        "prod_merc_positions_long", "prod_merc_positions_short", "swap_positions_long_all",
        "swap__positions_short_all", "other_rept_positions_long", "other_rept_positions_short",
    ])
    params = {
        "$where": "cftc_contract_market_code='088691'",
        "$select": select,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "156",
    }
    request = Request(
        CFTC_URL + "?" + urlencode(params),
        headers={"Accept": "application/json", "User-Agent": "GoldAI/1.0 (CFTC public data)"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw_rows = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise COTDataError("Could not retrieve the official CFTC gold positioning report.") from exc
    records = normalise_cot_rows(raw_rows)
    payload = {
        "symbol": "XAUUSD", "contract_code": GOLD_CONTRACT_CODE,
        "report_type": "Disaggregated futures-only",
        "source": "U.S. Commodity Futures Trading Commission",
        "source_dataset": "72hh-3qpy", "report_frequency": "Weekly",
        "position_as_of": records[-1]["report_date"],
        "expected_release_date": records[-1]["expected_release_date"],
        "count": len(records), "latest": records[-1], "history": records,
        "data_note": (
            "COT positions are weekly Tuesday snapshots normally published Friday. "
            "They are delayed positioning context, not live order flow or an entry signal. "
            "Holiday publication delays can occur; use actual release timestamps for backtests."
        ),
    }
    with _lock:
        _cache["at"], _cache["payload"] = time.monotonic(), payload
    return payload
