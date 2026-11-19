import unittest
import os
from unittest.mock import patch
from fastapi import HTTPException
from datetime import datetime, timezone
from pydantic import ValidationError
from mt5_ingest import MT5Batch, normalise_mt5_batch, archive_mt5_batch, MT5TickBatch, archive_mt5_tick_batch
import time
from main import ingest_mt5_candles, ingest_mt5_ticks


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

    def test_large_history_batch_is_accepted(self):
        candles = [
            {"time": 1767000000 + i * 60, "open": 4300, "high": 4302,
             "low": 4298, "close": 4301}
            for i in range(1200)
        ]
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5", "symbol": "XAUUSDm",
            "timeframe": "M1", "server_utc_offset_seconds": 0,
            "candles": candles,
        })
        self.assertEqual(len(batch.candles), 1200)

    def test_large_history_archive_is_split_into_500_row_writes(self):
        candles = [
            {"time": 1767000000 + i * 60, "open": 4300, "high": 4302,
             "low": 4298, "close": 4301}
            for i in range(1100)
        ]
        batch = MT5Batch.model_validate({
            "broker_server": "Broker-MT5", "symbol": "XAUUSDm",
            "timeframe": "M1", "server_utc_offset_seconds": 0,
            "candles": candles,
        })
        with patch("mt5_ingest._archive_reference_rows",
                   side_effect=lambda table, rows, conflict: {
                       "status": "saved", "rows_sent": len(rows)
                   }) as archive:
            result = archive_mt5_batch(batch)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["rows_sent"], 1100)
        self.assertEqual([len(call.args[1]) for call in archive.call_args_list], [500, 500, 100])


if __name__ == "__main__":
    unittest.main()


class MT5TickIngestionTests(unittest.TestCase):
    def test_valid_tick_batch_is_accepted_and_timestamp_is_milliseconds(self):
        now_msc = int(time.time() * 1000)
        batch = MT5TickBatch.model_validate({
            "broker_server": "Exness-MT5Trial9",
            "symbol": "XAUUSDm",
            "server_utc_offset_seconds": 0,
            "ticks": [{
                "time_msc": now_msc,
                "bid": 4300.10, "ask": 4300.25, "last": None,
                "volume": 0, "volume_real": 0, "flags": 6
            }]
        })
        self.assertEqual(batch.ticks[0].time_msc, now_msc)

    def test_invalid_crossed_quote_is_rejected(self):
        with self.assertRaises(ValidationError):
            MT5TickBatch.model_validate({
                "broker_server": "Exness-MT5Trial9",
                "symbol": "XAUUSDm",
                "server_utc_offset_seconds": 0,
                "ticks": [{"time_msc": int(time.time() * 1000),
                           "bid": 4301, "ask": 4300, "flags": 6}]
            })

    def test_tick_batch_is_limited_to_500(self):
        now_msc = int(time.time() * 1000)
        with self.assertRaises(ValidationError):
            MT5TickBatch.model_validate({
                "broker_server": "Exness-MT5Trial9",
                "symbol": "XAUUSDm",
                "server_utc_offset_seconds": 0,
                "ticks": [{"time_msc": now_msc + i, "bid": 4300, "ask": 4301}
                          for i in range(501)]
            })

    def test_tick_archive_writes_to_isolated_research_table(self):
        now_msc = int(time.time() * 1000)
        batch = MT5TickBatch.model_validate({
            "broker_server": "Exness-MT5Trial9",
            "symbol": "XAUUSDm",
            "server_utc_offset_seconds": 0,
            "ticks": [{"time_msc": now_msc, "bid": 4300.1, "ask": 4300.2, "flags": 6}]
        })
        with patch("mt5_ingest._archive_reference_rows",
                   return_value={"status": "saved", "rows_sent": 1}) as archive:
            result = archive_mt5_tick_batch(batch)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(archive.call_args.args[0], "mt5_ticks_research")
        self.assertEqual(archive.call_args.args[2], "symbol,source,tick_key")

    def test_tick_endpoint_requires_authentication(self):
        now_msc = int(time.time() * 1000)
        batch = MT5TickBatch.model_validate({
            "broker_server": "Exness-MT5Trial9",
            "symbol": "XAUUSDm",
            "server_utc_offset_seconds": 0,
            "ticks": [{"time_msc": now_msc, "bid": 4300.1, "ask": 4300.2}]
        })
        with patch.dict(os.environ, {"MT5_INGEST_TOKEN": ""}):
            with self.assertRaises(HTTPException) as error:
                ingest_mt5_ticks(batch, None)
        self.assertEqual(error.exception.status_code, 503)
