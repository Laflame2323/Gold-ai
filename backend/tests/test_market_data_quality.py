import copy
from datetime import datetime, timezone

import pytest

from market_data_quality import audit_candles


BASE = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())  # Monday


def rows(count=5, step=1800):
    return [{"time": BASE + i * step, "open": 2000.0, "high": 2001.0,
             "low": 1999.0, "close": 2000.5} for i in range(count)]


def test_clean_regular_series_has_stable_fingerprint():
    data = rows()
    first = audit_candles(data, timeframe_seconds=1800)
    second = audit_candles(copy.deepcopy(data), timeframe_seconds=1800)
    assert first["status"] == "clean"
    assert first["gap_count"] == 0
    assert first["dataset_payload_sha256"] == second["dataset_payload_sha256"]
    assert first["execution_enabled"] is False


def test_duplicate_timestamp_is_reported():
    data = rows()
    data[2]["time"] = data[1]["time"]
    result = audit_candles(data, timeframe_seconds=1800)
    assert result["status"] == "invalid"
    assert any(e["reason"] == "duplicate_timestamp" for e in result["errors"])


def test_out_of_order_timestamp_is_reported():
    data = rows()
    data[2], data[3] = data[3], data[2]
    result = audit_candles(data, timeframe_seconds=1800)
    assert any(e["reason"] == "out_of_order_timestamp" for e in result["errors"])


@pytest.mark.parametrize("patch,reason", [
    ({"high": 1998.0}, "invalid_ohlc_high"),
    ({"low": 2002.0}, "invalid_ohlc_low"),
    ({"close": float("nan")}, "invalid_close"),
    ({"open": -1}, "invalid_open"),
])
def test_invalid_ohlc_is_reported(patch, reason):
    data = rows()
    data[2].update(patch)
    result = audit_candles(data, timeframe_seconds=1800)
    assert result["status"] == "invalid"
    assert any(e["reason"] == reason for e in result["errors"])


def test_short_non_weekend_gap_is_reported_without_filling():
    data = rows()
    data[2]["time"] += 1800
    data[3]["time"] += 1800
    data[4]["time"] += 1800
    result = audit_candles(data, timeframe_seconds=1800)
    assert result["gap_count"] == 1
    assert result["gaps"][0]["expected_missing_bars"] == 1
    assert result["gaps"][0]["classification"] == "short_non_weekend_gap"
    assert result["status"] == "gaps_require_review"


def test_weekend_crossing_gap_is_classified_separately():
    friday = int(datetime(2026, 1, 9, 20, 0, tzinfo=timezone.utc).timestamp())
    monday = int(datetime(2026, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    data = rows(2)
    data[0]["time"] = friday
    data[1]["time"] = monday
    result = audit_candles(data, timeframe_seconds=1800)
    assert result["gap_count"] == 1
    assert result["gaps"][0]["weekend_boundary_crossed"] is True
    assert result["gaps"][0]["classification"] == "weekend_or_week_open_gap"


def test_non_weekend_large_gap_is_marked_unusual_not_assumed_invalid():
    data = rows(2)
    data[1]["time"] = data[0]["time"] + 6 * 1800
    result = audit_candles(data, timeframe_seconds=1800)
    assert result["gaps"][0]["classification"] == "unusual_non_weekend_gap"
    assert result["status"] == "gaps_require_review"


def test_irregular_gap_does_not_claim_exact_missing_bar_count():
    data = rows(2)
    data[1]["time"] += 1900
    result = audit_candles(data, timeframe_seconds=1800)
    assert result["gaps"][0]["interval_is_exact_multiple"] is False
    assert result["gaps"][0]["expected_missing_bars"] is None


def test_fingerprint_changes_when_input_data_changes():
    data = rows()
    first = audit_candles(data, timeframe_seconds=1800)["dataset_payload_sha256"]
    data[2]["close"] += 0.1
    second = audit_candles(data, timeframe_seconds=1800)["dataset_payload_sha256"]
    assert first != second


def test_rejects_invalid_audit_configuration():
    with pytest.raises(ValueError):
        audit_candles(rows(), timeframe_seconds=0)
    with pytest.raises(ValueError):
        audit_candles(rows(), timeframe_seconds=1800, unusual_gap_multiple=1)
