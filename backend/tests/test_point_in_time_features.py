import pytest

from point_in_time_features import align_completed_higher_timeframe


def candle(stamp, close):
    return {"time": stamp, "open": close - 1, "high": close, "low": close - 2, "close": close}


def test_intraday_decision_cannot_see_unfinished_daily_bar():
    day = 86_400
    daily = [candle(0, 100), candle(day, 200), candle(2 * day, 300)]
    lower = [candle(day + 10 * 3600, 150)]
    aligned = align_completed_higher_timeframe(lower, daily, 5 * 60, day)
    assert aligned == [daily[0]]


def test_daily_bar_becomes_available_only_after_its_close():
    day = 86_400
    daily = [candle(0, 100), candle(day, 200)]
    lower = [
        candle(day - 5 * 60, 110),
        candle(day, 120),
    ]
    aligned = align_completed_higher_timeframe(lower, daily, 5 * 60, day)
    assert aligned == [daily[0], daily[1]]


def test_future_daily_rows_do_not_change_past_alignment():
    day = 86_400
    lower = [candle(day + 9 * 3600, 120), candle(day + 15 * 3600, 130)]
    daily = [candle(0, 100), candle(day, 200), candle(2 * day, 300)]
    full = align_completed_higher_timeframe(lower, daily, 5 * 60, day)
    truncated = align_completed_higher_timeframe(lower, daily[:2], 5 * 60, day)
    assert full == truncated


def test_rejects_unsorted_or_duplicate_timestamps():
    with pytest.raises(ValueError, match="strictly increasing"):
        align_completed_higher_timeframe(
            [candle(60, 1), candle(60, 2)], [candle(0, 1)], 60, 3600
        )


def test_rejects_invalid_timeframe_lengths():
    with pytest.raises(ValueError, match="positive integer"):
        align_completed_higher_timeframe(
            [candle(60, 1)], [candle(0, 1)], 0, 3600
        )
