import time
import unittest

from analysis_engine import analyse_timeframes, REQUIRED_TIMEFRAMES


def make_payload(count=100, direction=1, data_status="recent", interval=900):
    candles = []
    for index in range(count):
        close = 2000 + direction * (index * 0.03 + index * index * 0.0003)
        candles.append({
            "time": int(time.time()) - (count - index) * interval,
            "open": close - direction * 0.05,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "volume": 1,
        })
    return {
        "candles": candles,
        "data_status": data_status,
        "last_candle_at": "2026-11-17T10:00:00+00:00",
    }


class AnalysisEngineTests(unittest.TestCase):
    def setUp(self):
        self.bullish_data = {
            timeframe: make_payload(direction=1)
            for timeframe in REQUIRED_TIMEFRAMES
        }

    def test_aligned_bullish_market_is_research_buy(self):
        result = analyse_timeframes(self.bullish_data)
        self.assertEqual(result["analysis_status"], "complete")
        self.assertEqual(result["research_signal"], "BUY")
        self.assertEqual(result["technical_bias"], "BULLISH")

    def test_stale_timeframe_forces_wait(self):
        data = dict(self.bullish_data)
        data["M1"] = make_payload(data_status="stale")
        result = analyse_timeframes(data)
        self.assertEqual(result["analysis_status"], "data_not_ready")
        self.assertEqual(result["research_signal"], "WAIT")

    def test_insufficient_history_forces_wait(self):
        data = dict(self.bullish_data)
        data["H4"] = make_payload(count=30)
        result = analyse_timeframes(data)
        self.assertEqual(result["research_signal"], "WAIT")
        self.assertEqual(result["timeframes"]["H4"]["status"], "insufficient_data")

    def test_missing_timeframe_forces_wait(self):
        data = dict(self.bullish_data)
        del data["H1"]
        result = analyse_timeframes(data)
        self.assertEqual(result["research_signal"], "WAIT")
        self.assertIn("H1", result["missing_timeframes"])



    def test_market_regime_requires_fresh_timeframes(self):
        from analysis_engine import _market_regime
        result = _market_regime({"H4":{"status":"stale_data"}}, 0.4)
        self.assertEqual(result["label"], "UNCONFIRMED")

    def test_market_regime_detects_bullish_trend(self):
        from analysis_engine import _market_regime
        results = {key:{"status":"ready","score":score}
                   for key,score in {"H4":3,"H1":2,"M15":2,"M5":1}.items()}
        result = _market_regime(results, 0.4)
        self.assertEqual(result["label"], "UPTREND")
        self.assertEqual(result["direction"], "BULLISH")

if __name__ == "__main__":
    unittest.main()
