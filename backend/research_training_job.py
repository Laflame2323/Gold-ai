"""Scheduled, research-only MT5 model training job.

Run from backend/: python research_training_job.py
The job never places orders and refuses stale broker candle archives.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from market_storage import (
    MarketStorageError,
    _supabase_credentials,
    get_latest_mt5_source,
    get_mt5_market_candles,
)
from triple_barrier_research import evaluate_triple_barrier_meta

TIMEFRAME_LIMITS = {"H4": 1000, "H1": 3000, "M30": 6000, "M15": 12000}


def _save_run(row: dict) -> None:
    base_url, api_key = _supabase_credentials()
    if not base_url or not api_key:
        raise RuntimeError("Supabase private credentials are not configured.")
    request = Request(
        f"{base_url}/rest/v1/research_training_runs",
        data=json.dumps(row, allow_nan=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        if response.status not in (200, 201, 204):
            raise RuntimeError(f"Training-run archive returned HTTP {response.status}.")


def run_training() -> dict:
    started = datetime.now(timezone.utc)
    source_info = get_latest_mt5_source()
    if not source_info:
        raise MarketStorageError("No authenticated MT5 candle source is archived.")

    symbol, source = source_info["symbol"], source_info["source"]
    candles_by_timeframe = {}
    freshness = {}
    for timeframe, limit in TIMEFRAME_LIMITS.items():
        market = get_mt5_market_candles(
            symbol, source, timeframe, max_candles=limit
        )
        freshness[timeframe] = {
            "count": market["count"],
            "last_candle_at": market["last_candle_at"],
            "age_seconds": market["age_seconds"],
            "data_status": market["data_status"],
        }
        if market["data_status"] != "recent":
            raise MarketStorageError(
                f"{timeframe} broker candles are stale; refusing to train on stale data."
            )
        candles_by_timeframe[timeframe] = market["candles"]

    with tempfile.TemporaryDirectory(prefix="gold-ai-training-") as temp_dir:
        artifact_path = Path(temp_dir) / "candidate.joblib"
        result = evaluate_triple_barrier_meta(
            candles_by_timeframe,
            horizon=24,
            pt_atr=1.5,
            sl_atr=1.0,
            base_timeframe="M30",
            candidate_model_path=str(artifact_path),
        )
        if result.get("status") != "complete" or not artifact_path.exists():
            status = "skipped"
            artifact_b64 = None
            artifact_sha = None
        else:
            status = "complete"
            artifact_bytes = artifact_path.read_bytes()
            artifact_b64 = base64.b64encode(artifact_bytes).decode("ascii")
            artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()

        finished = datetime.now(timezone.utc)
        row = {
            "symbol": symbol,
            "source": source,
            "base_timeframe": "M30",
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "status": status,
            "metrics": {
                "training_result": result,
                "timeframe_freshness": freshness,
                "training_policy": {
                    "schedule": "every 6 hours",
                    "target": "ATR triple-barrier meta-label candidate",
                    "stale_data_policy": "skip; never train on stale broker candles",
                    "promotion": "manual review only; no automatic production promotion",
                    "research_only": True,
                    "execution_enabled": False,
                },
            },
            "model_artifact_base64": artifact_b64,
            "model_sha256": artifact_sha,
        }
        _save_run(row)
        return {
            "status": status,
            "symbol": symbol,
            "source": source,
            "metrics": result,
            "model_sha256": artifact_sha,
            "archived": True,
            "research_only": True,
            "execution_enabled": False,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        print(json.dumps(run_training(), indent=2, allow_nan=False))
    except (MarketStorageError, HTTPError, URLError, OSError, ValueError, RuntimeError) as exc:
        logging.exception("GOLD_AI_RESEARCH_TRAINING_FAILED")
        raise SystemExit(1) from exc
