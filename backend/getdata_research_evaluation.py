"""Run a strictly chronological research evaluation on the public XAUUSD M1 sample.

The external OHLCV feed is kept separate from broker candles. Resampled bars
are accepted only when every constituent M1 minute is present.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

from triple_barrier_research import _atr, evaluate_triple_barrier_meta
from profit_aware_research import evaluate_profit_aware_meta


def load_m1(path: Path, ask_path: Path | None = None):
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if "datetime" in row:
                stamp = int(datetime.fromisoformat(
                    row["datetime"].replace("Z", "+00:00")
                ).timestamp())
            else:
                stamp = int(float(row["timestamp"]))
                if stamp > 100_000_000_000:
                    stamp //= 1000
            rows.append({
                "time": stamp,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0.0),
            })
    rows.sort(key=lambda item: item["time"])
    if len({row["time"] for row in rows}) != len(rows):
        raise ValueError("M1 source contains duplicate timestamps.")

    spread_audit = {
        "ask_file_used": bool(ask_path),
        "matched_bid_ask_minutes": 0,
        "unmatched_bid_minutes": len(rows),
        "mean_spread_price": None,
        "median_spread_price": None,
    }
    if ask_path:
        asks = {}
        with ask_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                stamp = int(float(row["timestamp"]))
                if stamp > 100_000_000_000:
                    stamp //= 1000
                asks[stamp] = {
                    "open": float(row["open"]),
                    "close": float(row["close"]),
                }
        spreads = []
        matched = 0
        for row in rows:
            ask = asks.get(row["time"])
            if ask is None:
                continue
            spread = ((ask["open"] - row["open"]) + (ask["close"] - row["close"])) / 2.0
            if not math.isfinite(spread) or spread <= 0:
                continue
            row["spread"] = spread
            spreads.append(spread)
            matched += 1
        spread_audit.update({
            "matched_bid_ask_minutes": matched,
            "unmatched_bid_minutes": len(rows) - matched,
            "mean_spread_price": (sum(spreads) / len(spreads)) if spreads else None,
            "median_spread_price": (
                sorted(spreads)[len(spreads) // 2] if spreads else None
            ),
        })
    return rows, spread_audit


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
            **({"spread": sum(r["spread"] for r in group) / len(group)}
               if all("spread" in r for r in group) else {}),
        })
    return output, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Bid or reference M1 CSV")
    parser.add_argument("--ask-input", help="Optional ask-side M1 CSV for observed spread estimation")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    ask_path = Path(args.ask_input) if args.ask_input else None
    m1, spread_audit = load_m1(Path(args.input), ask_path)
    if ask_path and spread_audit["matched_bid_ask_minutes"] < int(len(m1) * 0.95):
        raise SystemExit(
            "Bid/ask timestamp alignment is below 95%; refusing to estimate spread from mismatched data."
        )
    intervals = {"M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
    candles = {}
    rejected = {}
    for name, seconds in intervals.items():
        candles[name], rejected[name] = resample_complete(m1, seconds)

    m30_atr = [value for value in _atr(candles["M30"], 14) if value is not None]
    mean_m30_atr = sum(m30_atr) / len(m30_atr) if m30_atr else None
    spread_cost_atr = (
        spread_audit["mean_spread_price"] / mean_m30_atr
        if spread_audit["mean_spread_price"] is not None and mean_m30_atr
        else None
    )
    # Include observed Dukascopy bid/ask spread plus a 0.05 ATR allowance
    # for commissions/slippage, with a conservative 0.10 ATR floor.
    round_trip_cost_atr = max(0.10, spread_cost_atr + 0.05) if spread_cost_atr is not None else 0.10
    source_name = "Dukascopy XAUUSD M1 bid/ask" if ask_path else "GetData public XAUUSD M1 reference sample"

    report = {
        "source": source_name,
        "source_rows_m1": len(m1),
        "spread_audit": spread_audit,
        "mean_m30_atr_price": mean_m30_atr,
        "observed_spread_cost_atr": spread_cost_atr,
        "round_trip_cost_atr_used": round_trip_cost_atr,
        "complete_resampled_candles": {k: len(v) for k, v in candles.items()},
        "rejected_incomplete_time_buckets": rejected,
        "evaluations": {},
        "profit_aware_evaluations": {},
        "profit_aware_cost_scenarios_atr": [round_trip_cost_atr],
        "profit_aware_barrier_grid": [{"pt_atr": pt, "sl_atr": 1.0} for pt in (1.5, 2.0, 2.5, 3.0)],
        "research_only": True,
        "read_only": True,
        "execution_enabled": False,
        "production_model_persisted": False,
        "caveats": [
            "Dukascopy bid/ask is an independent reference feed, not Exness XAUUSDm execution data." if ask_path else "GetData reference OHLCV is not Exness XAUUSDm bid/ask.",
            "M1 volume is feed tick activity, not centralized traded volume.",
            "Observed Dukascopy spread is converted to ATR units and supplemented by a 0.05 ATR allowance; this remains an estimate, not Exness fills." if ask_path else "The 0.10 ATR cost is a conservative assumption, not an observed broker fill.",
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

    # Compare target distances using validation-only selection and a fixed 0.10 ATR cost assumption.
    # Each candidate's chronological test block remains untouched; the grid winner is chosen only
    # from its conservative validation expectancy lower bound.
    m30_grid = {}
    for pt_atr in (1.5, 2.0, 2.5, 3.0):
        key = f"M30_PT{pt_atr}_SL1.0_COST{round_trip_cost_atr:.4f}"
        result = evaluate_profit_aware_meta(
            candles, horizon=24, pt_atr=pt_atr, sl_atr=1.0,
            base_timeframe="M30", round_trip_cost_atr=round_trip_cost_atr,
        )
        if result.get("status") not in {"complete", "no_positive_validation_edge"}:
            raise SystemExit(f"{key} evaluation failed: {result}")
        m30_grid[key] = result

    qualified = [
        (key, result) for key, result in m30_grid.items()
        if result.get("status") == "complete"
        and result.get("validation_trade_metrics", {}).get("mean_net_r_lower_90_bound", -999) > 0
    ]
    if qualified:
        selected_key, selected_result = max(
            qualified,
            key=lambda pair: pair[1]["validation_trade_metrics"]["mean_net_r_lower_90_bound"],
        )
        report["profit_aware_grid_selection"] = {
            "status": "selected_on_validation",
            "selected_configuration": selected_key,
            "validation_trade_metrics": selected_result["validation_trade_metrics"],
            "test_used_for_selection": False,
        }
        for key, result in m30_grid.items():
            if key != selected_key and result.get("status") == "complete":
                result.pop("untouched_test", None)
                result.pop("test_cost_sensitivity", None)
                result.pop("accepted_barrier_outcomes", None)
    else:
        all_summaries = [
            {"configuration": key, **row}
            for key, result in m30_grid.items()
            for row in result.get("candidate_validation_summary", [])
        ]
        best_summary = max(
            all_summaries,
            key=lambda row: row.get("validation_lower_90_bound_net_r", -999),
            default=None,
        )
        report["profit_aware_grid_selection"] = {
            "status": "no_qualified_configuration",
            "message": "No M30 target-distance configuration passed conservative positive validation expectancy.",
            "best_validation_candidate": best_summary,
            "test_used_for_selection": False,
        }
    report["profit_aware_evaluations"].update(m30_grid)

    # H1 is a slower comparison using a 2 ATR target and 1 ATR stop.
    h1_result = evaluate_profit_aware_meta(
        candles, horizon=12, pt_atr=2.0, sl_atr=1.0,
        base_timeframe="H1", round_trip_cost_atr=round_trip_cost_atr,
    )
    report["profit_aware_evaluations"][f"H1_PT2.0_SL1.0_COST{round_trip_cost_atr:.4f}"] = h1_result
    if h1_result.get("status") not in {"complete", "no_positive_validation_edge"}:
        raise SystemExit(f"H1 evaluation failed: {h1_result}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"profit_aware_grid_selection": report["profit_aware_grid_selection"]}, indent=2))
    for configuration, result in report["profit_aware_evaluations"].items():
        summary = {
            "configuration": configuration,
            "status": result.get("status"),
            "message": result.get("message"),
            "selected_confidence_threshold": result.get("selected_confidence_threshold"),
            "validation_trade_metrics": result.get("validation_trade_metrics"),
            "candidate_validation_summary": result.get("candidate_validation_summary"),
            "untouched_test": result.get("untouched_test"),
            "test_cost_sensitivity": result.get("test_cost_sensitivity"),
            "split_samples": result.get("split_samples"),
            "split_decisions": result.get("split_decisions"),
        }
        print(json.dumps(summary, indent=2))

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
