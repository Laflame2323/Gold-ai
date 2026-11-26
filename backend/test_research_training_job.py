from unittest.mock import patch

import research_training_job as job


def test_training_refuses_stale_broker_candles():
    source = {"symbol": "XAUUSDm", "source": "MT5:Exness-MT5Trial9"}
    stale_market = {
        "count": 1000,
        "last_candle_at": "2026-11-19T00:00:00+00:00",
        "age_seconds": 600000,
        "data_status": "stale",
        "candles": [],
    }
    with patch.object(job, "get_latest_mt5_source", return_value=source), patch.object(
        job, "get_mt5_market_candles", return_value=stale_market
    ):
        try:
            job.run_training()
        except job.MarketStorageError as exc:
            assert "stale" in str(exc)
        else:
            raise AssertionError("Training must stop when broker candles are stale.")
