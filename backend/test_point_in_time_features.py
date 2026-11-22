import unittest

from point_in_time_features import align_completed_higher_timeframe


def candle(stamp, close):
    return {"time": stamp, "open": close - 1, "high": close, "low": close - 2, "close": close}


class PointInTimeFeatureTests(unittest.TestCase):
    def test_intraday_decision_cannot_see_unfinished_daily_bar(self):
        day = 86_400
        daily = [candle(0, 100), candle(day, 200), candle(2 * day, 300)]
        lower = [candle(day + 10 * 3600, 150)]
        aligned = align_completed_higher_timeframe(lower, daily, 5 * 60, day)
        self.assertEqual(aligned, [daily[0]])

    def test_daily_bar_becomes_available_only_after_its_close(self):
        day = 86_400
        daily = [candle(0, 100), candle(day, 200)]
        lower = [candle(day - 5 * 60, 110), candle(2 * day - 5 * 60, 120)]
        aligned = align_completed_higher_timeframe(lower, daily, 5 * 60, day)
        self.assertEqual(aligned, [daily[0], daily[1]])

    def test_future_daily_rows_do_not_change_past_alignment(self):
        day = 86_400
        lower = [candle(day + 9 * 3600, 120), candle(day + 15 * 3600, 130)]
        daily = [candle(0, 100), candle(day, 200), candle(2 * day, 300)]
        full = align_completed_higher_timeframe(lower, daily, 5 * 60, day)
        truncated = align_completed_higher_timeframe(lower, daily[:2], 5 * 60, day)
        self.assertEqual(full, truncated)

    def test_rejects_unsorted_or_duplicate_timestamps(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            align_completed_higher_timeframe(
                [candle(60, 1), candle(60, 2)], [candle(0, 1)], 60, 3600
            )

    def test_rejects_invalid_timeframe_lengths(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            align_completed_higher_timeframe([candle(60, 1)], [candle(0, 1)], 0, 3600)


if __name__ == "__main__":
    unittest.main()
