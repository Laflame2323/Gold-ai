import pytest

from multi_horizon_labels import build_directional_labels


def make_candles(count=40, interval=3600, start=1_700_000_000, close=2000.0):
    rows = []
    for i in range(count):
        rows.append({
            "time": start + i * interval,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        })
    return rows


def test_h1_horizon_uses_only_supported_one_two_four_hour_windows():
    candles = make_candles()
    for horizon in (1, 2, 4):
        result = build_directional_labels(candles, "H1", horizon)
        assert result["status"] == "complete"
        assert result["horizon_seconds"] == horizon * 3600
        assert result["event_count"] > 0


def test_m15_horizon_supports_fifteen_and_thirty_minutes():
    candles = make_candles(interval=900)
    result = build_directional_labels(candles, "M15", 2)
    assert result["status"] == "complete"
    assert result["horizon_seconds"] == 1800


def test_future_price_reaching_upper_barrier_labels_long():
    candles = make_candles()
    # First event is decision at index 13, entry at 14; ATR is 2.
    candles[14]["high"] = 2005.0
    result = build_directional_labels(candles, "H1", 1)
    event = next(item for item in result["events"] if item["decision_index"] == 13)
    assert event["label"] == 1
    assert event["reason"] == "upper_barrier_first"


def test_future_price_reaching_lower_barrier_labels_short():
    candles = make_candles()
    candles[14]["low"] = 1995.0
    result = build_directional_labels(candles, "H1", 1)
    event = next(item for item in result["events"] if item["decision_index"] == 13)
    assert event["label"] == -1
    assert event["reason"] == "lower_barrier_first"


def test_same_bar_touching_both_barriers_is_neutral():
    candles = make_candles()
    candles[14]["high"] = 2005.0
    candles[14]["low"] = 1995.0
    result = build_directional_labels(candles, "H1", 1)
    event = next(item for item in result["events"] if item["decision_index"] == 13)
    assert event["label"] == 0
    assert event["reason"] == "ambiguous_same_bar"


def test_session_gap_invalidates_event_instead_of_bridging_it():
    candles = make_candles()
    for index in range(14, len(candles)):
        candles[index]["time"] += 3600
    result = build_directional_labels(candles, "H1", 1)
    assert result["excluded_counts"]["missing_or_session_gap"] > 0
    assert not any(item["decision_index"] == 13 for item in result["events"])


def test_future_changes_do_not_change_earlier_feature_or_entry_fields():
    candles = make_candles()
    baseline = build_directional_labels(candles, "H1", 1)
    altered = [dict(row) for row in candles]
    altered[-1]["high"] += 100
    altered[-1]["low"] -= 100
    changed = build_directional_labels(altered, "H1", 1)
    first = baseline["events"][0]
    matching = next(item for item in changed["events"]
                    if item["decision_index"] == first["decision_index"])
    assert first["atr"] == matching["atr"]
    assert first["entry_price"] == matching["entry_price"]


def test_rejects_unsupported_horizon_and_bad_ohlc():
    with pytest.raises(ValueError, match="unsupported"):
        build_directional_labels(make_candles(), "H1", 3)
    with pytest.raises(ValueError, match="unsupported"):
        build_directional_labels(make_candles(), "H1", 1.0)
    candles = make_candles()
    candles[0]["high"] = 1000
    with pytest.raises(ValueError, match="invalid high"):
        build_directional_labels(candles, "H1", 1)
