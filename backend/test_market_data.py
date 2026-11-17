import unittest

from market_data import MarketDataError, _aggregate_h4, _normalise_candles


class MarketDataTests(unittest.TestCase):
    def test_normalise_sorts_and_deduplicates(self):
        rows = [
            {"t": 120, "o": 2, "h": 3, "l": 1, "c": 2.5},
            {"t": 60, "o": 1, "h": 2, "l": 0.5, "c": 1.5},
            {"t": 60, "o": 1, "h": 2.2, "l": 0.5, "c": 1.6},
        ]
        result = _normalise_candles(rows)
        self.assertEqual([item["time"] for item in result], [60, 120])
        self.assertEqual(result[0]["close"], 1.6)

    def test_h4_aggregation(self):
        start = (1_800_000_000 // 14_400) * 14_400
        rows = [
            {
                "time": start + index * 3600,
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
                "volume": 10,
            }
            for index in range(4)
        ]
        result = _aggregate_h4(rows, now=start + 14_400)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["open"], 100)
        self.assertEqual(result[0]["close"], 104)
        self.assertEqual(result[0]["high"], 105)
        self.assertEqual(result[0]["low"], 99)
        self.assertEqual(result[0]["volume"], 40)

    def test_h4_skips_still_forming_group(self):
        start = (1_800_000_000 // 14_400) * 14_400
        rows = [
            {
                "time": start + index * 3600,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": None,
            }
            for index in range(4)
        ]
        with self.assertRaises(MarketDataError):
            _aggregate_h4(rows, now=start + 3 * 3600 + 1800)

    def test_h4_skips_incomplete_group(self):
        start = (1_800_000_000 // 14_400) * 14_400
        rows = [
            {
                "time": start + index * 3600,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": None,
            }
            for index in range(3)
        ]
        with self.assertRaises(MarketDataError):
            _aggregate_h4(rows, now=start + 14_400)


if __name__ == "__main__":
    unittest.main()
