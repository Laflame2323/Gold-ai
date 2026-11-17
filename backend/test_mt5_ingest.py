import unittest
from datetime import datetime, timezone
from pydantic import ValidationError
from mt5_ingest import MT5Batch, normalise_mt5_batch


class MT5IngestionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_valid_closed_broker_candle_is_tagged(self):
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5Live01",
            "symbol": "XAUUSDm",
            "timeframe": "M5",
            "candles": [{
                "time": 1767225300,
                "open": 4300.0, "high": 4302.0,
                "low": 4298.0, "close": 4301.0,
                "tick_volume": 120, "real_volume": 0, "spread_points": 25
            }]
        })
        rows = normalise_mt5_batch(batch, self.now)
        self.assertEqual(rows[0]["source"], "MT5:Broker-MT5Live01")
        self.assertEqual(rows[0]["quality_status"], "verified")
        self.assertTrue(rows[0]["is_closed"])
        self.assertEqual(rows[0]["raw_metadata"]["spread_points"], 25)

    def test_invalid_ohlc_is_rejected(self):
        with self.assertRaises(ValidationError):
            MT5Batch.model_validate({
                "broker_server": "Broker-MT5",
                "symbol": "XAUUSD",
                "timeframe": "M1",
                "candles": [{
                    "time": 1767225540,
                    "open": 4300, "high": 4299,
                    "low": 4298, "close": 4301
                }]
            })

    def test_future_or_forming_candle_is_rejected(self):
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5",
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "candles": [{
                "time": 1767225540,
                "open": 4300, "high": 4302,
                "low": 4298, "close": 4301
            }]
        })
        with self.assertRaises(ValueError):
            normalise_mt5_batch(batch, self.now)

    def test_unsupported_timeframe_is_rejected(self):
        with self.assertRaises(ValidationError):
            MT5Batch.model_validate({
                "broker_server": "Broker-MT5", "symbol": "XAUUSD",
                "timeframe": "D1",
                "candles": [{"time": 1767225540, "open": 1, "high": 2, "low": 1, "close": 2}]
            })


if __name__ == "__main__":
    unittest.main()
