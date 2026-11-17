import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


def broker_payload(symbol, source, timeframe):
    candles = []
    start = 1_795_000_000
    for index in range(80):
        close = 4000.0 + index * 0.1
        candles.append({
            "time": start + index * 60,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10,
        })
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
        "data_status": "recent",
        "age_seconds": 10,
        "source": "authenticated MT5 broker feed",
        "provider_source": source,
    }


class BrokerAnalysisTests(unittest.TestCase):
    @patch("main.get_market_candles")
    @patch("main.get_mt5_market_candles")
    @patch("main.get_latest_mt5_source", return_value={
        "symbol": "XAUUSDm",
        "source": "MT5:Broker MT5 Demo",
        "fetched_at": "2026-11-17T15:00:00+00:00",
    })
    def test_analysis_uses_one_broker_feed_for_all_timeframes(
        self, latest_source, get_broker, get_reference
    ):
        get_broker.side_effect = lambda symbol, source, timeframe: broker_payload(
            symbol, source, timeframe
        )

        result = main.analyse()

        self.assertEqual(result["symbol"], "XAUUSDm")
        self.assertEqual(result["data_source"], "Authenticated MT5 broker feed (read-only)")
        self.assertEqual(result["signal"], "WAIT")
        self.assertFalse(result["execution_ready"])
        self.assertFalse(result["ai_trained"])
        self.assertEqual(get_broker.call_count, 6)
        get_reference.assert_not_called()

    @patch("main.get_market_candles")
    @patch("main.get_mt5_market_candles", return_value={
        "symbol": "XAUUSDm", "timeframe": "M1", "candles": [], "count": 0
    })
    @patch("main.get_latest_mt5_source", return_value={
        "symbol": "XAUUSDm", "source": "MT5:Broker MT5 Demo"
    })
    def test_chart_does_not_fall_back_to_reference_when_broker_source_exists(
        self, latest_source, get_broker, get_reference
    ):
        with self.assertRaises(HTTPException) as raised:
            main.market_candles("M1")

        self.assertEqual(raised.exception.status_code, 503)
        get_reference.assert_not_called()


if __name__ == "__main__":
    unittest.main()
