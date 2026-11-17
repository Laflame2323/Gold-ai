"""Public daily macro-market context from FRED; delayed, read-only research data."""
from __future__ import annotations
import csv
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = {
    "DGS10": {"label": "US 10Y Treasury yield", "unit": "%", "description": "Nominal long-term US government yield"},
    "DFII10": {"label": "US 10Y real yield", "unit": "%", "description": "Inflation-protected Treasury yield"},
    "DTWEXBGS": {"label": "US dollar broad index", "unit": "index", "description": "Trade-weighted broad US dollar index"},
    "VIXCLS": {"label": "CBOE VIX", "unit": "index", "description": "US equity-market implied volatility gauge"},
}
MACRO_CACHE_SECONDS = 6 * 60 * 60
_cache = {"at": 0.0, "payload": None}
_lock = threading.Lock()


class MacroDataError(Exception):
    """Raised when macro data is unavailable or malformed."""


def parse_fred_csv(text, series_id):
    if series_id not in FRED_SERIES:
        raise MacroDataError("Unsupported FRED series.")
    rows = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "observation_date" not in reader.fieldnames:
            raise MacroDataError("Unexpected FRED CSV header.")
        for raw in reader:
            try:
                observed = date.fromisoformat(raw["observation_date"][:10])
                raw_value = raw.get(series_id)
                if raw_value is None or raw_value.strip() in ("", "."):
                    continue
                value = float(raw_value)
                if not (-1_000_000 < value < 1_000_000):
                    continue
                rows.append({
                    "series_id": series_id,
                    "observation_date": observed.isoformat(),
                    "value": value,
                })
            except (TypeError, ValueError, KeyError):
                continue
    except (csv.Error, TypeError) as exc:
        raise MacroDataError("Could not parse FRED observations.") from exc
    unique = {row["observation_date"]: row for row in rows}
    result = [unique[key] for key in sorted(unique)]
    if not result:
        raise MacroDataError(f"No valid observations received for {series_id}.")
    return result


def _fetch_series(series_id, start_date, end_date):
    query = urlencode({"id": series_id, "cosd": start_date, "coed": end_date})
    request = Request(
        FRED_CSV_URL + "?" + query,
        headers={"User-Agent": "GoldAI/1.0 (public FRED macro context)", "Accept": "text/csv"},
    )
    try:
        with urlopen(request, timeout=25) as response:
            content = response.read().decode("utf-8-sig")
    except Exception as exc:
        raise MacroDataError(f"FRED request failed for {series_id}.") from exc
    return parse_fred_csv(content, series_id)


def get_macro_context(force_refresh=False):
    now = time.monotonic()
    with _lock:
        if not force_refresh and _cache["payload"] is not None and now - _cache["at"] < MACRO_CACHE_SECONDS:
            return _cache["payload"]
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 3 + 2)
    history = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(_fetch_series, sid, start_date.isoformat(), end_date.isoformat()): sid
                for sid in FRED_SERIES}
        for job in as_completed(jobs):
            sid = jobs[job]
            try:
                history[sid] = job.result()
            except MacroDataError as exc:
                errors[sid] = str(exc)
    latest = {}
    for sid, observations in history.items():
        latest[sid] = {
            **observations[-1],
            **FRED_SERIES[sid],
            "change_20_observations": (
                round(observations[-1]["value"] - observations[-21]["value"], 4)
                if len(observations) > 20 else None
            ),
        }
    if not latest:
        raise MacroDataError("All FRED macro series are currently unavailable.")
    payload = {
        "source": "Federal Reserve Bank of St. Louis FRED",
        "source_url": "https://fred.stlouisfed.org/",
        "as_of": max(item["observation_date"] for item in latest.values()),
        "series": latest,
        "history": history,
        "errors": errors,
        "data_note": (
            "Daily macro observations are published with delays and may have different dates. "
            "Treasury yields and the dollar are context variables, not direct XAUUSD signals. "
            "The VIX measures equity volatility, not gold volatility. Missing observations are not filled."
        ),
    }
    with _lock:
        _cache["at"], _cache["payload"] = time.monotonic(), payload
    return payload
