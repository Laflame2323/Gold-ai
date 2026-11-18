import unittest
from unittest.mock import patch

from fastapi import HTTPException
import main
from test_research_backtest import trend_candles


class ResearchHoldoutEndpointTests(unittest.TestCase):
    @patch("main.get_market_candles")
    @patch("main.get_latest_mt5_source", return_value=None)
    def test_holdout_uses_reference_feed_when_no_broker_source(self, _source, get_market):
        get_market.return_value = {"symbol": "XAUUSD", "candles": trend_candles(600)}
        result = main.research_backtest_holdout("H1", 5, 0.25)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["data_source"], "XAUS reference-market feed (not broker execution prices)")
        self.assertEqual(result["timeframe"], "H1")
        self.assertFalse(result["execution_enabled"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["ai_trained"])
        self.assertFalse(result["accuracy_is_live"])
        self.assertEqual(result["model_type"], "rule_based_research_baseline")
        self.assertIn("untouched_holdout", result)

    @patch("main.get_mt5_market_candles")
    @patch("main.get_latest_mt5_source", return_value={"symbol": "XAUUSDm", "source": "MT5:Test"})
    def test_holdout_prefers_single_broker_archive(self, _source, get_market):
        get_market.return_value = {"symbol": "XAUUSDm", "candles": trend_candles(600)}
        result = main.research_backtest_holdout("M30", 5, 0.25)
        self.assertEqual(result["symbol"], "XAUUSDm")
        self.assertEqual(result["data_source"], "Authenticated MT5 broker archive (read-only)")
        self.assertEqual(result["broker_source"], "MT5:Test")
        self.assertFalse(result["execution_enabled"])

    def test_unsupported_timeframe_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            main.research_backtest_holdout("D1", 5, 0.25)
        self.assertEqual(raised.exception.status_code, 400)

    def test_invalid_horizon_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            main.research_backtest_holdout("H1", 0, 0.25)
        self.assertEqual(raised.exception.status_code, 400)

    def test_invalid_holdout_fraction_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            main.research_backtest_holdout("H1", 5, 0.75)
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
