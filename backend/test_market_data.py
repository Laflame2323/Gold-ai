import unittest
from unittest.mock import patch

from market_data import MarketDataError, _aggregate_h4, _normalise_candles, _fetch_json_with_retries, _fetch_provider_candles


class MarketDataTests(unittest.TestCase):

    def test_history_fetch_retries_transient_failure(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"ok": true}'

        with patch("market_data.urlopen", side_effect=[TimeoutError("temporary"), FakeResponse()]) as fetch:
            with patch("market_data.time.sleep"):
                result = _fetch_json_with_retries(object(), "failed", attempts=2)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(fetch.call_count, 2)

    def test_history_fetch_does_not_hide_repeated_failures(self):
        with patch("market_data.urlopen", side_effect=TimeoutError("offline")) as fetch:
            with patch("market_data.time.sleep"):
                with self.assertRaises(MarketDataError):
                    _fetch_json_with_retries(object(), "provider unavailable", attempts=3)
        self.assertEqual(fetch.call_count, 3)

    def test_chart_candle_fetch_uses_retry_helper(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"points":[{"t":1794891600,"o":4000,"h":4002,"l":3998,"c":4001}]}'

        with patch("market_data._cache", {}):
            with patch("market_data._fetch_json_with_retries", return_value={
                "points": [{"t": 1794891600, "o": 4000, "h": 4002, "l": 3998, "c": 4001}]
            }) as retry_fetch:
                result = _fetch_provider_candles("1m", "1d")
        self.assertEqual(len(result["candles"]), 1)
        self.assertEqual(result["candles"][0]["close"], 4001.0)
        retry_fetch.assert_called_once()
        self.assertEqual(retry_fetch.call_args.kwargs["attempts"], 3)
        self.assertEqual(retry_fetch.call_args.kwargs["timeout"], 20)

    def test_normalise_sorts_and_deduplicates(self):
        rows = [
            {"t": 120, "o": 2, "h": 3, "l": 1, "c": 2.5},
            {"t": 60, "o": 1, "h": 2, "l": 0.5, "c": 1.5},
            {"t": 60, "o": 1, "h": 2.2, "l": 0.5, "c": 1.6},
        ]
        result = _normalise_candles(rows)
        self.assertEqual([item["time"] for item in result], [60, 120])
        self.assertEqual(result[0]["close"], 1.6)

    def test_normalise_rejects_zero_or_negative_prices(self):
        rows = [
            {"t": 60, "o": 0, "h": 2, "l": 0.5, "c": 1},
            {"t": 120, "o": 2, "h": 3, "l": -1, "c": 2},
        ]
        with self.assertRaises(MarketDataError):
            _normalise_candles(rows)

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
