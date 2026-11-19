"""Train and evaluate research-only XAUUSD candidates on audited HistData M1.

The broker's Exness archive is deliberately not read by this script. The input
is the independent, fixed-EST HistData M1 archive normalized to UTC.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from triple_barrier_research import evaluate_triple_barrier_meta


TIMEFRAMES = {
    "M15": ("15min", 15),
    "M30": ("30min", 30),
    "H1": ("1h", 60),
    "H4": ("4h", 240),
}


def resample_complete(frame: pd.DataFrame, timeframe: str):
    rule, expected_minutes = TIMEFRAMES[timeframe]
    indexed = frame.set_index("timestamp")
    grouped = indexed.resample(rule, origin="epoch", label="left", closed="left")
    bars = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        minute_count=("close", "count"),
    )
    complete = bars.loc[bars["minute_count"] == expected_minutes].drop(columns=["minute_count"])
    rejected = int(len(bars) - len(complete))
    result = [
        {
            "time": int(stamp.timestamp()),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
        }
        for stamp, row in complete.iterrows()
    ]
    return result, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Audited UTC HistData parquet")
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidate-model-output", required=True)
    args = parser.parse_args()

    source = Path(args.input)
    frame = pd.read_parquet(source, columns=["timestamp", "open", "high", "low", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if frame["timestamp"].duplicated().any():
        raise ValueError("Audited input still contains duplicate timestamps")

    candles = {}
    rejected = {}
    for timeframe in TIMEFRAMES:
        candles[timeframe], rejected[timeframe] = resample_complete(frame, timeframe)

    report = {
        "source": "HistData XAUUSD M1, independent of Exness",
        "source_rows_m1": int(len(frame)),
        "source_first_utc": frame["timestamp"].iloc[0].isoformat(),
        "source_last_utc": frame["timestamp"].iloc[-1].isoformat(),
        "complete_resampled_candles": {k: len(v) for k, v in candles.items()},
        "rejected_incomplete_time_buckets": rejected,
        "exness_data_used": False,
        "research_only": True,
        "read_only": True,
        "candidate_model_trained": False,
        "candidate_model_saved_for_external_test": False,
        "production_model_persisted": False,
        "execution_enabled": False,
        "evaluations": {},
        "caveats": [
            "HistData source is bid OHLC; its published volume field is zero and is excluded.",
            "No ask-side spread, commission, slippage or swap is included.",
            "The final chronological test is from this historical source, not Exness.",
            "Meta-model accuracy is not directional prediction accuracy or net trading profitability.",
            "Exness remains reserved for a separate later broker-specific test.",
        ],
    }

    for base_tf, horizon in (("M30", 24), ("H1", 12)):
        result = evaluate_triple_barrier_meta(
            candles,
            horizon=horizon,
            pt_atr=1.5,
            sl_atr=1.0,
            base_timeframe=base_tf,
            candidate_model_path=str(Path(args.candidate_model_output).with_name(
                f"gold_ai_{base_tf.lower()}_histdata_candidate.joblib"
            )),
        )
        report["evaluations"][base_tf] = result
        if result.get("status") != "complete":
            raise SystemExit(f"{base_tf} evaluation incomplete: {result}")
        report["candidate_model_trained"] = True
        report["candidate_model_saved_for_external_test"] = True

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "source_rows_m1": report["source_rows_m1"],
        "complete_resampled_candles": report["complete_resampled_candles"],
        "evaluations": {
            tf: {
                "eligible_samples": result["eligible_samples"],
                "split_samples": result["split_samples"],
                "meta_model_test": result["meta_model_test"],
                "test_majority_baseline_accuracy_pct": result["test_majority_baseline_accuracy_pct"],
                "primary_test_meta_label_win_rate_pct": result["primary_test_meta_label_win_rate_pct"],
                "confidence_coverage": result["confidence_coverage"],
                "selected_parameters": result["selected_parameters"],
            }
            for tf, result in report["evaluations"].items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
