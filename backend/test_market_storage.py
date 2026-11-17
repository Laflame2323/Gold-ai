import unittest
from unittest.mock import patch

import market_storage


class FakeResponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MarketStorageTests(unittest.TestCase):
    def setUp(self):
        with market_storage._candle_archive_lock:
            market_storage._candle_archive_cache.clear()
        self.market = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "provider_source": "XAUS chart API",
            "data_status": "recent",
            "age_seconds": 10,
            "candles": [
                {"time": 1794891600, "open": 4000, "high": 4002, "low": 3998, "close": 4001, "volume": 10},
                {"time": 1794891660, "open": 4001, "high": 4003, "low": 3999, "close": 4002, "volume": 11},
            ],
        }

    @patch("market_storage.urlopen", return_value=FakeResponse())
    @patch("market_storage._supabase_credentials", return_value=("https://example.supabase.co", "service-key"))
    def test_identical_candle_window_is_archived_once(self, credentials, fetch):
        first = market_storage.archive_market_candles(self.market)
        second = market_storage.archive_market_candles(self.market)

        self.assertEqual(first["status"], "saved")
        self.assertEqual(first["rows_sent"], 2)
        self.assertEqual(second["status"], "saved")
        self.assertEqual(second["rows_sent"], 0)
        self.assertTrue(second["deduplicated"])
        self.assertEqual(fetch.call_count, 1)

    @patch("market_storage.urlopen", return_value=FakeResponse())
    @patch("market_storage._supabase_credentials", return_value=("https://example.supabase.co", "service-key"))
    def test_changed_candle_window_is_archived_again(self, credentials, fetch):
        market_storage.archive_market_candles(self.market)
        changed = {
            **self.market,
            "candles": [dict(candle) for candle in self.market["candles"]],
        }
        changed["candles"][-1]["close"] = 4002.5

        result = market_storage.archive_market_candles(changed)

        self.assertEqual(result["rows_sent"], 2)
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
