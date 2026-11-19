"""Score HistData-trained research candidates on a separate external XAUUSD sample.

This script never fits or tunes a model on the external dataset.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
from getdata_research_evaluation import load_m1, resample_complete
from triple_barrier_research import _make_samples, _metrics
from causal_smc_features import FEATURE_NAMES as SMC_FEATURE_NAMES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    candidate = joblib.load(args.candidate_model)
    base_tf = candidate["base_timeframe"]
    horizon = int(candidate["horizon"])
    pt_atr = float(candidate["pt_atr"])
    sl_atr = float(candidate["sl_atr"])

    m1 = load_m1(Path(args.input))
    intervals = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
    candles = {}
    rejected = {}
    for name, seconds in intervals.items():
        candles[name], rejected[name] = resample_complete(m1, seconds)

    sample, error = _make_samples(candles, horizon, pt_atr, sl_atr, base_tf)
    if error:
        raise SystemExit(f"External evaluation incomplete: {error}")

    expected_names = sample["aligned"]["feature_names"] + SMC_FEATURE_NAMES
    if candidate["feature_names"] != expected_names:
        raise ValueError("External feature schema does not match saved HistData candidate")

    labels = [int(outcome == side) for outcome, side in zip(sample["outcomes"], sample["sides"])]
    predictions = candidate["model"].predict(sample["x"]).astype(int).tolist()
    probabilities = candidate["model"].predict_proba(sample["x"])[:, list(candidate["model"].classes_).index(1)]
    metrics = _metrics(labels, predictions)
    baseline = max(labels.count(0), labels.count(1)) / len(labels) * 100
    coverage = []
    for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
        selected = probabilities >= threshold
        count = int(selected.sum())
        wins = sum(labels[i] for i, keep in enumerate(selected) if keep)
        coverage.append({
            "meta_probability_threshold": threshold,
            "accepted_samples": count,
            "coverage_pct": round(count / len(labels) * 100, 2),
            "accepted_trade_win_rate_pct": round(wins / count * 100, 2) if count else None,
        })

    report = {
        "source": "GetData public XAUUSD M1 sample",
        "source_rows_m1": len(m1),
        "complete_resampled_candles": {k: len(v) for k, v in candles.items()},
        "rejected_incomplete_time_buckets": rejected,
        "external_test_samples": len(labels),
        "histdata_candidate_training_rows": candidate["training_rows"],
        "base_timeframe": base_tf,
        "horizon": horizon,
        "meta_model_external_test": metrics,
        "external_majority_baseline_accuracy_pct": round(baseline, 2),
        "primary_rule_external_meta_label_win_rate_pct": round(sum(labels) / len(labels) * 100, 2),
        "confidence_coverage": coverage,
        "model_retrained_on_external_data": False,
        "external_data_used_for_tuning": False,
        "exness_data_used": False,
        "research_only": True,
        "read_only": True,
        "production_model_persisted": False,
        "execution_enabled": False,
        "caveats": [
            "This is a separate public feed, not Exness XAUUSDm bid/ask.",
            "External sample is evaluated with a HistData-trained model; no refit or tuning occurs here.",
            "No spread, commission, slippage or swap costs are modeled.",
            "Meta-label classification accuracy is not directional accuracy or net profitability.",
            "HistData mirror provenance is not independently complete.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "base_timeframe": base_tf,
        "external_test_samples": len(labels),
        "meta_model_external_test": metrics,
        "external_majority_baseline_accuracy_pct": round(baseline, 2),
        "primary_rule_external_meta_label_win_rate_pct": round(sum(labels) / len(labels) * 100, 2),
        "confidence_coverage": coverage,
        "model_retrained_on_external_data": False,
        "external_data_used_for_tuning": False,
    }, indent=2))


if __name__ == "__main__":
    main()
