import unittest

from multitimeframe_features import build_multitimeframe_features


def candles(count, interval, start=1_700_000_000):
    rows = []
    price = 2300.0
    for index in range(count):
        next_price = price + (0.15 if index % 3 else -0.08)
        rows.append({
            "time": start + index * interval,
            "open": price,
            "high": max(price, next_price) + 0.1,
            "low": min(price, next_price) - 0.1,
            "close": next_price,
        })
        price = next_price
    return rows


class MultiTimeframeFeatureTests(unittest.TestCase):
    def test_builds_aligned_features_with_expected_shape(self):
        data = {
            "H4": candles(100, 14400),
            "H1": candles(400, 3600),
            "M30": candles(800, 1800),
            "M15": candles(1600, 900),
        }
        result = build_multitimeframe_features(data)
        self.assertGreater(result["row_count"], 0)
        self.assertEqual(len(result["feature_names"]), 36)
        self.assertEqual(len(result["rows"][0]["features"]), 36)
        self.assertTrue(result["research_only"])

    def test_never_uses_a_candle_that_has_not_closed(self):
        data = {
            "H4": candles(100, 14400),
            "H1": candles(400, 3600),
            "M30": candles(800, 1800),
            "M15": candles(1600, 900),
        }
        result = build_multitimeframe_features(data)
        for row in result["rows"]:
            for timeframe, source_open in row["source_candle_times"].items():
                interval = {"H4": 14400, "H1": 3600, "M30": 1800, "M15": 900}[timeframe]
                self.assertLessEqual(source_open + interval, row["decision_time"])

    def test_future_higher_timeframe_candle_cannot_change_past_features(self):
        data = {
            "H4": candles(100, 14400),
            "H1": candles(400, 3600),
            "M30": candles(800, 1800),
            "M15": candles(1600, 900),
        }
        original = build_multitimeframe_features(data)
        extended = {key: list(value) for key, value in data.items()}
        future_time = extended["H4"][-1]["time"] + 14400
        last_close = extended["H4"][-1]["close"]
        extended["H4"].append({
            "time": future_time, "open": last_close,
            "high": last_close + 0.2, "low": last_close - 0.1,
            "close": last_close + 0.1,
        })
        with_future = build_multitimeframe_features(extended)
        self.assertEqual(original["rows"], with_future["rows"])

    def test_missing_timeframe_is_rejected(self):
        with self.assertRaises(ValueError):
            build_multitimeframe_features({"H1": candles(100, 3600)})

    def test_out_of_order_candles_are_rejected(self):
        data = {
            "H4": candles(100, 14400),
            "H1": candles(400, 3600),
            "M30": candles(800, 1800),
            "M15": candles(1600, 900),
        }
        data["M15"][5], data["M15"][6] = data["M15"][6], data["M15"][5]
        with self.assertRaises(ValueError):
            build_multitimeframe_features(data)


if __name__ == "__main__":
    unittest.main()
