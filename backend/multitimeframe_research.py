"""Experimental multi-timeframe logistic research evaluator.

This module is intentionally separate from the production API. It evaluates
completed H4/H1/M30/M15 features against H1 outcomes with chronological,
purged splits and training-only scaling.
"""
from __future__ import annotations

from multitimeframe_features import build_multitimeframe_features, TIMEFRAME_SECONDS
from research_ml import (
    MIN_ROWS_PER_SPLIT, _fit_logistic, _score,
    _confidence_coverage, _probability_summary,
)


def _fit_scaler(rows):
    width = len(rows[0])
    means = [sum(row[j] for row in rows) / len(rows) for j in range(width)]
    scales = []
    for j, mean in enumerate(means):
        variance = sum((row[j] - mean) ** 2 for row in rows) / len(rows)
        scales.append(variance ** 0.5 or 1.0)
    return means, scales


def _transform(rows, means, scales):
    return [[(row[j] - means[j]) / scales[j] for j in range(len(means))]
            for row in rows]


def _walk_forward(rows, labels, decision_indices, candle_count, horizon):
    # Split within the actual multi-timeframe overlap, not the full H1 archive.
    # Sparse/shorter M15 or M30 history must not push every aligned row into
    # the final test block.
    aligned_start = min(decision_indices)
    aligned_end = max(decision_indices) + 1
    aligned_span = aligned_end - aligned_start
    boundaries = [aligned_start + int(aligned_span * fraction)
                  for fraction in (0.30, 0.40, 0.50, 0.60, 0.70)]
    folds = []
    for number, (train_end, test_end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        train_pos = [i for i, d in enumerate(decision_indices) if d < train_end - horizon]
        test_pos = [i for i, d in enumerate(decision_indices)
                    if train_end + horizon <= d < test_end - horizon]
        y_train = [labels[i] for i in train_pos]
        y_test = [labels[i] for i in test_pos]
        if min(len(train_pos), len(test_pos)) < MIN_ROWS_PER_SPLIT or len(set(y_train)) < 2:
            folds.append({"fold": number, "status": "insufficient_data",
                          "train_samples": len(train_pos), "test_samples": len(test_pos)})
            continue
        x_train = [rows[i] for i in train_pos]
        x_test = [rows[i] for i in test_pos]
        means, scales = _fit_scaler(x_train)
        weights = _fit_logistic(_transform(x_train, means, scales), y_train)
        metrics = _score(_transform(x_test, means, scales), y_test, weights)
        majority = 1 if sum(y_train) >= len(y_train) / 2 else 0
        baseline = sum(y == majority for y in y_test) / len(y_test) * 100
        folds.append({
            "fold": number, "status": "complete",
            "training_end_candle_index": train_end,
            "test_end_candle_index_exclusive": test_end,
            "train_samples": len(train_pos), "test_samples": len(test_pos),
            "metrics": metrics,
            "train_majority_baseline_accuracy_pct": round(baseline, 2),
            "accuracy_minus_baseline_pct_points": round(metrics["accuracy_pct"] - baseline, 2),
            "scaler_fit_on": "this fold's training block only",
        })
    complete = [fold for fold in folds if fold["status"] == "complete"]
    return {
        "method": "expanding training window with sequential purged test windows",
        "completed_folds": len(complete), "total_folds": len(folds), "folds": folds,
        "mean_fold_accuracy_pct": round(sum(x["metrics"]["accuracy_pct"] for x in complete) / len(complete), 2) if complete else None,
        "mean_fold_balanced_accuracy_pct": round(sum(x["metrics"]["balanced_accuracy_pct"] for x in complete) / len(complete), 2) if complete else None,
    }




def _fit_balanced_logistic(rows, labels, epochs=1200, learning_rate=0.04, l2=0.01):
    """Fit logistic regression with inverse-frequency class weights."""
    import numpy as np

    features = np.asarray(rows, dtype=np.float64)
    targets = np.asarray(labels, dtype=np.float64)
    positives = max(1, int(np.sum(targets == 1)))
    negatives = max(1, int(np.sum(targets == 0)))
    weights_by_class = {0.0: len(targets) / (2.0 * negatives),
                        1.0: len(targets) / (2.0 * positives)}
    sample_weights = np.asarray([weights_by_class[float(y)] for y in targets])
    normalizer = float(np.sum(sample_weights))
    coefficients = np.zeros(features.shape[1], dtype=np.float64)
    bias = 0.0
    for _ in range(epochs):
        logits = np.clip(bias + features @ coefficients, -60.0, 60.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        errors = (probabilities - targets) * sample_weights
        bias_gradient = float(np.sum(errors) / normalizer)
        coefficient_gradient = (features.T @ errors) / normalizer + l2 * coefficients
        bias -= learning_rate * bias_gradient
        coefficients -= learning_rate * coefficient_gradient
    return [float(bias), *[float(value) for value in coefficients]]

def _validation_ablation(rows, labels, train_positions, validation_positions):
    """Select features and class weighting on validation only."""
    groups = {
        "H1": list(range(9, 18)),
        "H4": list(range(0, 9)),
        "M30": list(range(18, 27)),
        "M15": list(range(27, 36)),
    }
    configurations = (
        ("H1_only", ("H1",)),
        ("H4_H1", ("H4", "H1")),
        ("H1_M30_M15", ("H1", "M30", "M15")),
        ("all_timeframes", ("H4", "H1", "M30", "M15")),
    )
    train_labels = [labels[i] for i in train_positions]
    validation_labels = [labels[i] for i in validation_positions]
    majority = 1 if sum(train_labels) >= len(train_labels) / 2 else 0
    baseline = sum(y == majority for y in validation_labels) / len(validation_labels) * 100.0
    reports = []
    for name, timeframes in configurations:
        columns = [column for timeframe in timeframes for column in groups[timeframe]]
        train_rows = [[rows[i][column] for column in columns] for i in train_positions]
        validation_rows = [[rows[i][column] for column in columns] for i in validation_positions]
        means, scales = _fit_scaler(train_rows)
        train_x = _transform(train_rows, means, scales)
        validation_x = _transform(validation_rows, means, scales)
        for balanced in (False, True):
            weights = (_fit_balanced_logistic(train_x, train_labels)
                       if balanced else _fit_logistic(train_x, train_labels))
            metrics = _score(validation_x, validation_labels, weights)
            reports.append({
                "candidate": name + ("_class_balanced" if balanced else "_standard"),
                "timeframes": list(timeframes),
                "feature_count": len(columns),
                "class_weighting": "inverse_frequency" if balanced else "none",
                "validation": metrics,
                "training_majority_baseline_accuracy_pct": round(baseline, 2),
                "validation_accuracy_minus_baseline_pct_points": round(
                    metrics["accuracy_pct"] - baseline, 2
                ),
                "scaler_fit_on": "training block only",
            })
    ranked = sorted(
        reports,
        key=lambda item: (
            item["validation"]["balanced_accuracy_pct"],
            item["validation"]["accuracy_pct"],
            -item["feature_count"],
        ),
        reverse=True,
    )
    best = ranked[0]
    return {
        "selection_rule": "highest validation balanced accuracy; accuracy breaks ties; fewer features breaks remaining ties",
        "candidates": reports,
        "best_validation_candidate": best["candidate"],
        "selected_timeframes": best["timeframes"],
        "selected_class_weighting": best["class_weighting"],
        "warning": "Exploratory validation-only model and feature selection. The test set is evaluated once using the selected candidate; future unseen data is still required before promotion.",
    }


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
    # Chronological splits are based on the time range with complete,
    # leakage-safe MTF features. The full H1 history can be much older than
    # the shortest timeframe archive.
    aligned_start = min(decision_indices)
    aligned_end = max(decision_indices) + 1
    aligned_span = aligned_end - aligned_start
    train_boundary = aligned_start + int(aligned_span * 0.70)
    validation_boundary = aligned_start + int(aligned_span * 0.85)
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

    ablation = _validation_ablation(rows, labels, train_positions, validation_positions)
    timeframe_columns = {"H4": list(range(0, 9)), "H1": list(range(9, 18)),
                         "M30": list(range(18, 27)), "M15": list(range(27, 36))}
    selected_columns = [column for timeframe in ablation["selected_timeframes"]
                        for column in timeframe_columns[timeframe]]
    train_rows = [[row[column] for column in selected_columns] for row in train_rows]
    validation_rows = [[row[column] for column in selected_columns] for row in validation_rows]
    test_rows = [[row[column] for column in selected_columns] for row in test_rows]
    means, scales = _fit_scaler(train_rows)
    train_x = _transform(train_rows, means, scales)
    validation_x = _transform(validation_rows, means, scales)
    test_x = _transform(test_rows, means, scales)
    balanced_selected = ablation["selected_class_weighting"] == "inverse_frequency"
    weights = (_fit_balanced_logistic(train_x, train_labels)
               if balanced_selected else _fit_logistic(train_x, train_labels))
    diagnostics = {"feature_count": len(selected_columns),
                   "selected_timeframes": ablation["selected_timeframes"],
                   "selected_class_weighting": ablation["selected_class_weighting"],
                   "scaler_fit_on": "training block only"}
    train_metrics = _score(train_x, train_labels, weights)
    validation_metrics = _score(validation_x, validation_labels, weights)
    test_metrics = _score(test_x, test_labels, weights)
    majority = 1 if sum(train_labels) >= len(train_labels) / 2 else 0
    baseline = sum(label == majority for label in test_labels) / len(test_labels) * 100.0

    # Development walk-forward evaluation uses the aligned rows and original H1 indices.
    walk = _walk_forward(rows, labels, decision_indices, candle_count, horizon)
    return {
        "status": "complete",
        "model_type": "validation_selected_logistic_research_candidate",
        "candidate_model_trained": True,
        "ai_trained": False,
        "production_model_persisted": False,
        "timeframes": aligned["timeframes"],
        "feature_names": [aligned["feature_names"][column] for column in selected_columns],
        "feature_count": len(selected_columns),
        "feature_alignment": aligned["alignment_rule"],
        "horizon_candles": horizon,
        "neutral_zone_min_move_pct": float(min_move_pct),
        "excluded_small_move_outcomes": excluded,
        "eligible_samples": len(rows),
        "split_samples": split_sizes,
        "purge_candles_each_boundary": horizon,
        "scaler_fit_on": "training block only",
        "walk_forward": walk,
        "walk_forward_note": "Diagnostic fixed all-feature standard-logistic baseline; it is not the validation-selected final candidate reported in untouched_test.",
        "validation_ablation": ablation,
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
