import unittest
import os
from unittest.mock import patch
from fastapi import HTTPException
from datetime import datetime, timezone
from pydantic import ValidationError
from mt5_ingest import MT5Batch, normalise_mt5_batch
from main import ingest_mt5_candles


class MT5IngestionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_valid_closed_broker_candle_is_tagged(self):
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5Live01",
            "symbol": "XAUUSDm",
            "timeframe": "M5",
            "server_utc_offset_seconds": 7200,
            "candles": [{
                "time": 1767225300,
                "open": 4300.0, "high": 4302.0,
                "low": 4298.0, "close": 4301.0,
                "tick_volume": 120, "real_volume": 0, "spread_points": 25
            }]
        })
        rows = normalise_mt5_batch(batch, self.now)
        self.assertEqual(rows[0]["source"], "MT5:Broker-MT5Live01")
        self.assertEqual(rows[0]["candle_time"], "2025-12-31T21:55:00+00:00")
        self.assertEqual(rows[0]["quality_status"], "verified")
        self.assertTrue(rows[0]["is_closed"])
        self.assertEqual(rows[0]["raw_metadata"]["spread_points"], 25)
        self.assertEqual(rows[0]["raw_metadata"]["server_utc_offset_seconds"], 7200)

    def test_common_broker_names_and_gold_suffixes_are_accepted(self):
        batch = MT5Batch.model_validate({
            "broker_server": "Broker MT5 Demo",
            "symbol": "XAUUSD#",
            "timeframe": "M1",
            "server_utc_offset_seconds": 0,
            "candles": [{
                "time": 1767225540,
                "open": 1, "high": 2, "low": 1, "close": 2
            }]
        })
        self.assertEqual(batch.broker_server, "Broker MT5 Demo")
        self.assertEqual(batch.symbol, "XAUUSD#")

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
            "server_utc_offset_seconds": 0,
            "candles": [{
                "time": 1767225540,
                "open": 4300, "high": 4302,
                "low": 4298, "close": 4301
            }]
        })
        with self.assertRaises(ValueError):
            normalise_mt5_batch(batch, self.now)


    def test_ingestion_is_locked_when_token_is_not_configured(self):
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5", "symbol": "XAUUSD", "timeframe": "M1",
            "server_utc_offset_seconds": 0,
            "candles": [{"time": 1767225540, "open": 1, "high": 2, "low": 1, "close": 2}]
        })
        with patch.dict(os.environ, {"MT5_INGEST_TOKEN": ""}):
            with self.assertRaises(HTTPException) as error:
                ingest_mt5_candles(batch, None)
        self.assertEqual(error.exception.status_code, 503)

    def test_invalid_ingestion_token_is_rejected(self):
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5", "symbol": "XAUUSD", "timeframe": "M1",
            "server_utc_offset_seconds": 0,
            "candles": [{"time": 1767225540, "open": 1, "high": 2, "low": 1, "close": 2}]
        })
        with patch.dict(os.environ, {"MT5_INGEST_TOKEN": "expected-secret"}):
            with self.assertRaises(HTTPException) as error:
                ingest_mt5_candles(batch, "wrong-secret")
        self.assertEqual(error.exception.status_code, 401)

    def test_broker_utc_offset_is_required(self):
        with self.assertRaises(ValidationError):
            MT5Batch.model_validate({
                "broker_server": "Broker-MT5", "symbol": "XAUUSD", "timeframe": "M1",
                "candles": [{"time": 1767225540, "open": 1, "high": 2, "low": 1, "close": 2}]
            })

    def test_unsupported_timeframe_is_rejected(self):
        with self.assertRaises(ValidationError):
            MT5Batch.model_validate({
                "broker_server": "Broker-MT5", "symbol": "XAUUSD",
                "timeframe": "D1",
                "candles": [{"time": 1767225540, "open": 1, "high": 2, "low": 1, "close": 2}]
            })


if __name__ == "__main__":
    unittest.main()
