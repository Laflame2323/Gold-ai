import unittest
from datetime import datetime, timezone
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

    @patch("market_storage._read_supabase_rows")
    def test_latest_mt5_source_is_selected_from_private_archive(self, read_rows):
        read_rows.return_value = [{
            "symbol": "XAUUSDm",
            "source": "MT5:Broker MT5 Demo",
            "fetched_at": "2026-11-17T15:00:00+00:00",
        }]

        result = market_storage.get_latest_mt5_source()

        self.assertEqual(result["symbol"], "XAUUSDm")
        self.assertEqual(result["source"], "MT5:Broker MT5 Demo")
        self.assertIn("source=like.MT5", read_rows.call_args.args[0])

    def test_mt5_timeframes_require_all_fresh_nonempty_feeds(self):
        required = ["M1", "M5", "M15"]
        fresh = {
            timeframe: {"data_status": "recent", "candles": [{"time": 1}]}
            for timeframe in required
        }
        self.assertTrue(market_storage.mt5_timeframes_are_fresh(fresh, required))
        stale = {**fresh, "M5": {"data_status": "stale", "candles": [{"time": 1}]}}
        self.assertFalse(market_storage.mt5_timeframes_are_fresh(stale, required))
        missing = {**fresh, "M15": {"data_status": "recent", "candles": []}}
        self.assertFalse(market_storage.mt5_timeframes_are_fresh(missing, required))
        self.assertFalse(market_storage.mt5_timeframes_are_fresh(fresh, ["M1", "H4"]))

    @patch("market_storage._read_supabase_rows")
    def test_mt5_candles_are_sorted_and_freshness_checked(self, read_rows):
        read_rows.return_value = [
            {
                "candle_time": "2026-11-17T15:04:00+00:00",
                "open": 4001, "high": 4003, "low": 4000, "close": 4002,
                "volume": 15, "quality_status": "verified", "is_closed": True,
            },
            {
                "candle_time": "2026-11-17T15:03:00+00:00",
                "open": 4000, "high": 4002, "low": 3999, "close": 4001,
                "volume": 12, "quality_status": "verified", "is_closed": True,
            },
        ]

        result = market_storage.get_mt5_market_candles(
            "XAUUSDm",
            "MT5:Broker MT5 Demo",
            "M1",
            now=datetime(2026, 11, 17, 15, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual([candle["time"] for candle in result["candles"]], sorted(
            candle["time"] for candle in result["candles"]
        ))
        self.assertEqual(result["data_status"], "recent")
        self.assertEqual(result["source"], "authenticated MT5 broker feed")

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
