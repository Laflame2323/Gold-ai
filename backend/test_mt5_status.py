import os
import unittest
from unittest.mock import patch

import main


class MT5StatusTests(unittest.TestCase):
    @patch("main.get_latest_mt5_source", return_value=None)
    def test_status_reports_locked_when_token_missing(self, get_source):
        with patch.dict(os.environ, {"MT5_INGEST_TOKEN": ""}):
            result = main.mt5_status()

        self.assertFalse(result["ingestion_configured"])
        self.assertTrue(result["ingestion_locked"])
        self.assertFalse(result["broker_feed_available"])
        self.assertFalse(result["execution_enabled"])
        self.assertTrue(result["read_only"])

    @patch("main.get_latest_mt5_source", return_value={
        "symbol": "XAUUSDm",
        "source": "MT5:Broker MT5 Demo",
        "fetched_at": "2026-11-17T15:00:00+00:00",
    })
    def test_status_reports_feed_without_exposing_secret(self, get_source):
        with patch.dict(os.environ, {"MT5_INGEST_TOKEN": "a-private-test-token"}):
            result = main.mt5_status()

        self.assertTrue(result["ingestion_configured"])
        self.assertFalse(result["ingestion_locked"])
        self.assertTrue(result["broker_feed_available"])
        self.assertEqual(result["symbol"], "XAUUSDm")
        self.assertNotIn("token", str(result).lower())
        self.assertFalse(result["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
