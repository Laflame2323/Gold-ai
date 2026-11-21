"""Run a strictly chronological research evaluation on the public XAUUSD M1 sample.

The external OHLCV feed is kept separate from broker candles. Resampled bars
are accepted only when every constituent M1 minute is present.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from triple_barrier_research import evaluate_triple_barrier_meta
from profit_aware_research import evaluate_profit_aware_meta


def load_m1(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            stamp = datetime.fromisoformat(row["datetime"].replace("Z", "+00:00"))
            rows.append({
                "time": int(stamp.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda item: item["time"])
    if len({row["time"] for row in rows}) != len(rows):
        raise ValueError("M1 source contains duplicate timestamps.")
    return rows


def resample_complete(m1, interval_seconds: int):
    expected = interval_seconds // 60
    buckets = {}
    for row in m1:
        bucket = row["time"] // interval_seconds * interval_seconds
        buckets.setdefault(bucket, []).append(row)
    output = []
    rejected = 0
    for bucket, group in sorted(buckets.items()):
        group.sort(key=lambda item: item["time"])
        expected_times = [bucket + 60 * offset for offset in range(expected)]
        if len(group) != expected or [r["time"] for r in group] != expected_times:
            rejected += 1
            continue
        output.append({
            "time": bucket,
            "open": group[0]["open"],
            "high": max(r["high"] for r in group),
            "low": min(r["low"] for r in group),
            "close": group[-1]["close"],
            "volume": sum(r["volume"] for r in group),
        })
    return output, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    m1 = load_m1(Path(args.input))
    intervals = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
    candles = {}
    rejected = {}
    for name, seconds in intervals.items():
        candles[name], rejected[name] = resample_complete(m1, seconds)

    report = {
        "source": "GetData public XAUUSD M1 sample",
        "source_rows_m1": len(m1),
        "complete_resampled_candles": {k: len(v) for k, v in candles.items()},
        "rejected_incomplete_time_buckets": rejected,
        "evaluations": {},
        "profit_aware_evaluations": {},
        "profit_aware_cost_scenarios_atr": [0.0, 0.05, 0.10],
        "research_only": True,
        "read_only": True,
        "execution_enabled": False,
        "production_model_persisted": False,
        "caveats": [
            "External mid-quote-style OHLCV source; not Exness XAUUSDm bid/ask.",
            "M1 volume is feed tick activity, not centralized traded volume.",
            "The profit-aware candidate is evaluated at explicit ATR-cost scenarios; these are sensitivity assumptions, not observed broker fills.",
            "Actual Exness spread, commission, slippage and swap must be measured before profitability can be claimed.",
            "Results are historical research, not live or forward performance.",
            "No test-set tuning; candidate selection uses validation only.",
        ],
    }

    for base_tf, horizon in (("M30", 24), ("H1", 12)):
        result = evaluate_triple_barrier_meta(
            candles, horizon=horizon, pt_atr=1.5, sl_atr=1.0,
            base_timeframe=base_tf,
        )
        report["evaluations"][base_tf] = result
        if result.get("status") != "complete":
            raise SystemExit(f"{base_tf} evaluation incomplete: {result}")

    # Independently test the profit-aware candidate on public historical gold data.
    # Costs are explicit ATR-fraction scenarios because this source has no broker
    # bid/ask or commission history. This is not a substitute for Exness MT5 data.
    for cost_atr in (0.0, 0.05, 0.10):
        result = evaluate_profit_aware_meta(
            candles, horizon=24, pt_atr=1.5, sl_atr=1.0,
            base_timeframe="M30", round_trip_cost_atr=cost_atr,
        )
        report["profit_aware_evaluations"][str(cost_atr)] = result
        if result.get("status") != "complete":
            raise SystemExit(
                f"Profit-aware M30 evaluation at cost {cost_atr} ATR incomplete: {result}"
            )

    # Compare a slower H1 decision rule over the same approximate holding horizon.
    h1_result = evaluate_profit_aware_meta(
        candles, horizon=12, pt_atr=1.5, sl_atr=1.0,
        base_timeframe="H1", round_trip_cost_atr=0.10,
    )
    report["profit_aware_evaluations"]["H1@0.10"] = h1_result
    if h1_result.get("status") != "complete":
        raise SystemExit(f"Profit-aware H1 evaluation incomplete: {h1_result}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    for cost_atr, result in report["profit_aware_evaluations"].items():
        print(json.dumps({
            "profit_aware_cost_atr": cost_atr,
            "selected_confidence_threshold": result["selected_confidence_threshold"],
            "validation_positive_net_expectancy": result["validation_positive_net_expectancy"],
            "validation_trade_metrics": result["validation_trade_metrics"],
            "untouched_test": result["untouched_test"],
            "accepted_barrier_outcomes": result["accepted_barrier_outcomes"],
            "test_cost_sensitivity": result["test_cost_sensitivity"],
            "split_samples": result["split_samples"],
        }, indent=2))

    for tf, result in report["evaluations"].items():
        print(json.dumps({
            "timeframe": tf,
            "eligible_samples": result["eligible_samples"],
            "split_samples": result["split_samples"],
            "meta_model_test": result["meta_model_test"],
            "test_majority_baseline_accuracy_pct": result["test_majority_baseline_accuracy_pct"],
            "primary_test_meta_label_win_rate_pct": result["primary_test_meta_label_win_rate_pct"],
            "confidence_coverage": result["confidence_coverage"],
            "selected_parameters": result["selected_parameters"],
        }, indent=2))


if __name__ == "__main__":
    main()
