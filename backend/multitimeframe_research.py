"""Experimental multi-timeframe logistic research evaluator.

This module is intentionally separate from the production API. It evaluates
completed H4/H1/M30/M15 features against H1 outcomes with chronological,
purged splits and training-only scaling.
"""
from __future__ import annotations

from multitimeframe_features import build_multitimeframe_features, TIMEFRAME_SECONDS
from research_ml import (
    MIN_ROWS_PER_SPLIT, _fit_scaler, _transform, _fit_logistic, _score,
    _confidence_coverage, _walk_forward_evaluate, _probability_summary,
)


def evaluate_multitimeframe_research(candles_by_timeframe, horizon=5, min_move_pct=0.0):
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 1 and 100")
    if isinstance(min_move_pct, bool) or not isinstance(min_move_pct, (int, float)) or not 0 <= min_move_pct <= 10:
        raise ValueError("min_move_pct must be between 0 and 10")
    base = candles_by_timeframe.get("H1")
    if not isinstance(base, list):
        raise ValueError("H1 candle history is required")
    if len(base) < 1000:
        return {"status": "insufficient_data", "candle_count": len(base),
                "minimum_candles": 1000, "ai_trained": False,
                "message": "At least 1,000 H1 candles are required."}

    aligned = build_multitimeframe_features(
        candles_by_timeframe, base_timeframe="H1",
        timeframes=("H4", "H1", "M30", "M15"),
    )
    base_by_decision = {
        int(candle["time"]) + TIMEFRAME_SECONDS["H1"]: (index, candle)
        for index, candle in enumerate(base)
    }
    rows, labels, decision_indices = [], [], []
    excluded = 0
    for item in aligned["rows"]:
        pair = base_by_decision.get(item["decision_time"])
        if pair is None:
            continue
        index, _ = pair
        if index + horizon >= len(base):
            continue
        entry = float(base[index + 1]["open"])
        exit_price = float(base[index + horizon]["close"])
        move_pct = (exit_price / entry - 1.0) * 100.0
        if abs(move_pct) <= float(min_move_pct):
            excluded += 1
            continue
        rows.append(item["features"])
        labels.append(1 if exit_price > entry else 0)
        decision_indices.append(index)

    candle_count = len(base)
    train_boundary = int(candle_count * 0.70)
    validation_boundary = int(candle_count * 0.85)
    train_positions = [i for i, d in enumerate(decision_indices) if d < train_boundary - horizon]
    validation_positions = [i for i, d in enumerate(decision_indices)
                            if train_boundary + horizon <= d < validation_boundary - horizon]
    test_positions = [i for i, d in enumerate(decision_indices) if d >= validation_boundary + horizon]
    split_sizes = {"train": len(train_positions), "validation": len(validation_positions),
                   "test": len(test_positions)}
    if min(split_sizes.values()) < MIN_ROWS_PER_SPLIT:
        return {"status": "insufficient_data", "candle_count": candle_count,
                "eligible_samples": len(rows), "split_samples": split_sizes,
                "minimum_samples_per_split": MIN_ROWS_PER_SPLIT, "ai_trained": False,
                "feature_alignment": aligned["alignment_rule"]}

    train_rows = [rows[i] for i in train_positions]
    train_labels = [labels[i] for i in train_positions]
    if len(set(train_labels)) < 2:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "Training block contains only one direction."}
    validation_rows = [rows[i] for i in validation_positions]
    validation_labels = [labels[i] for i in validation_positions]
    test_rows = [rows[i] for i in test_positions]
    test_labels = [labels[i] for i in test_positions]

    means, scales = _fit_scaler(train_rows)
    train_x = _transform(train_rows, means, scales)
    validation_x = _transform(validation_rows, means, scales)
    test_x = _transform(test_rows, means, scales)
    weights, diagnostics = _fit_logistic(train_x, train_labels, return_diagnostics=True)
    train_metrics = _score(train_x, train_labels, weights)
    validation_metrics = _score(validation_x, validation_labels, weights)
    test_metrics = _score(test_x, test_labels, weights)
    majority = 1 if sum(train_labels) >= len(train_labels) / 2 else 0
    baseline = sum(label == majority for label in test_labels) / len(test_labels) * 100.0

    # Development walk-forward evaluation uses the aligned rows and original H1 indices.
    walk = _walk_forward_evaluate(rows, labels, decision_indices, candle_count, horizon)
    return {
        "status": "complete",
        "model_type": "multi_timeframe_logistic_research_candidate",
        "candidate_model_trained": True,
        "ai_trained": False,
        "production_model_persisted": False,
        "timeframes": aligned["timeframes"],
        "feature_names": aligned["feature_names"],
        "feature_count": len(aligned["feature_names"]),
        "feature_alignment": aligned["alignment_rule"],
        "horizon_candles": horizon,
        "neutral_zone_min_move_pct": float(min_move_pct),
        "excluded_small_move_outcomes": excluded,
        "eligible_samples": len(rows),
        "split_samples": split_sizes,
        "purge_candles_each_boundary": horizon,
        "scaler_fit_on": "training block only",
        "walk_forward": walk,
        "train": train_metrics,
        "validation": validation_metrics,
        "untouched_test": test_metrics,
        "test_majority_baseline_accuracy_pct": round(baseline, 2),
        "test_accuracy_minus_baseline_pct_points": round(test_metrics["accuracy_pct"] - baseline, 2),
        "confidence_coverage": _confidence_coverage(test_x, test_labels, weights),
        "probability_diagnostics": {
            "train": _probability_summary(train_x, weights),
            "validation": _probability_summary(validation_x, weights),
            "untouched_test": _probability_summary(test_x, weights),
        },
        "fit_diagnostics": diagnostics,
        "limitations": [
            "Experimental multi-timeframe candidate; not connected to production inference.",
            "No spreads, commissions, slippage or swaps are included.",
            "Historical results do not guarantee future performance.",
        ],
        "research_only": True,
        "read_only": True,
        "execution_enabled": False,
    }
