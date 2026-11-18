"""Leakage-aware logistic-regression research evaluator (NumPy-accelerated fitting).

Features use information available at each completed decision candle. Labels
use the next candle open through the configured horizon close. Scaling is fit
on training rows only; chronological validation/test blocks are separated by
a horizon-sized purge. This evaluator never persists a production model.
"""
from __future__ import annotations

import math


FEATURE_NAMES = (
    "return_1", "return_3", "return_5", "return_10",
    "ema_gap_10", "ema_gap_30", "rsi_14",
    "range_pct", "body_pct", "volatility_10",
)
MIN_CANDLES = 1000
MIN_ROWS_PER_SPLIT = 50


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for item in values[period:]:
        value += alpha * (item - value)
    return value


def _rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    gain = sum(gains[:period]) / period
    loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        gain = ((period - 1) * gain + gains[i]) / period
        loss = ((period - 1) * loss + losses[i]) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _features(candles, index):
    # A bounded 200-candle warm-up keeps the research endpoint responsive on
    # small hosted instances while retaining enough history for EMA30/RSI14.
    # The slice ends at the decision candle, so no future data can enter.
    window_start = max(0, index - 199)
    window = candles[window_start:index + 1]
    closes = [float(row["close"]) for row in window]
    current = closes[-1]
    if current <= 0:
        raise ValueError("Candle prices must be positive.")
    def ret(period):
        return current / closes[-period - 1] - 1.0
    ema10, ema30 = _ema(closes, 10), _ema(closes, 30)
    row = window[-1]
    candle_range = (float(row["high"]) - float(row["low"])) / current
    body = (float(row["close"]) - float(row["open"])) / current
    changes = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - 10, len(closes))]
    volatility = math.sqrt(sum(x * x for x in changes) / len(changes))
    return [
        ret(1), ret(3), ret(5), ret(10),
        current / ema10 - 1.0, current / ema30 - 1.0,
        (_rsi(closes) - 50.0) / 50.0,
        candle_range, body, volatility,
    ]

def _sigmoid(value):
    if value >= 0:
        z = math.exp(-min(value, 60.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -60.0))
    return z / (1.0 + z)


def _fit_scaler(rows):
    means = [sum(row[j] for row in rows) / len(rows) for j in range(len(FEATURE_NAMES))]
    scales = []
    for j, mean in enumerate(means):
        variance = sum((row[j] - mean) ** 2 for row in rows) / len(rows)
        scales.append(math.sqrt(variance) or 1.0)
    return means, scales


def _transform(rows, means, scales):
    return [[(row[j] - means[j]) / scales[j] for j in range(len(means))] for row in rows]


def _fit_logistic(rows, labels, epochs=1200, learning_rate=0.04, l2=0.01, return_diagnostics=False):
    """Vectorized batch logistic fit with a 1200-epoch ceiling and early stopping."""
    import numpy as np

    features = np.asarray(rows, dtype=np.float64)
    targets = np.asarray(labels, dtype=np.float64)
    count = features.shape[0]
    coefficients = np.zeros(features.shape[1], dtype=np.float64)
    bias = 0.0
    stable_epochs = 0
    epochs_used = 0
    max_gradient = None

    for epoch in range(epochs):
        epochs_used = epoch + 1
        logits = bias + features @ coefficients
        # Match _sigmoid's bounded exponent and avoid numerical overflow.
        logits = np.clip(logits, -60.0, 60.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        errors = probabilities - targets
        bias_gradient = float(np.mean(errors))
        feature_gradients = (features.T @ errors) / count
        max_gradient = max(
            abs(bias_gradient),
            float(np.max(np.abs(feature_gradients))) if feature_gradients.size else 0.0,
        )

        bias -= learning_rate * bias_gradient
        coefficients -= learning_rate * (feature_gradients + l2 * coefficients)

        # Keep the convergence rule; allow more iterations before declaring non-convergence.
        stable_epochs = stable_epochs + 1 if max_gradient < 0.001 else 0
        if stable_epochs >= 8:
            break

    weights = [float(bias), *[float(value) for value in coefficients]]
    if return_diagnostics:
        return weights, {
            "epochs_used": epochs_used,
            "epoch_limit": epochs,
            "last_pre_update_max_gradient": round(float(max_gradient), 8) if max_gradient is not None else None,
            "converged": stable_epochs >= 8,
            "bias": round(float(bias), 8),
            "coefficients": {name: round(float(value), 8) for name, value in zip(FEATURE_NAMES, coefficients)},
        }
    return weights


def _probability_summary(rows, weights):
    probabilities = sorted(
        _sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], row)))
        for row in rows
    )
    if not probabilities:
        return {"samples": 0}
    def percentile(fraction):
        position = (len(probabilities) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(probabilities) - 1)
        part = position - lower
        return probabilities[lower] * (1.0 - part) + probabilities[upper] * part
    return {
        "samples": len(probabilities),
        "mean": round(sum(probabilities) / len(probabilities), 6),
        "min": round(probabilities[0], 6),
        "p10": round(percentile(0.10), 6),
        "median": round(percentile(0.50), 6),
        "p90": round(percentile(0.90), 6),
        "max": round(probabilities[-1], 6),
    }


def _score(rows, labels, weights):
    predictions = [
        1 if _sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], row))) >= 0.5 else 0
        for row in rows
    ]
    tp = sum(p == 1 and y == 1 for p, y in zip(predictions, labels))
    tn = sum(p == 0 and y == 0 for p, y in zip(predictions, labels))
    fp = sum(p == 1 and y == 0 for p, y in zip(predictions, labels))
    fn = sum(p == 0 and y == 1 for p, y in zip(predictions, labels))
    total = len(labels)
    accuracy = (tp + tn) / total * 100.0 if total else None
    recall_up = tp / (tp + fn) if tp + fn else 0.0
    recall_down = tn / (tn + fp) if tn + fp else 0.0
    precision_up = tp / (tp + fp) if tp + fp else 0.0
    precision_down = tn / (tn + fn) if tn + fn else 0.0
    return {
        "samples": total,
        "accuracy_pct": round(accuracy, 2) if accuracy is not None else None,
        "balanced_accuracy_pct": round((recall_up + recall_down) * 50.0, 2),
        "precision": {"up": round(precision_up * 100.0, 2),
                      "down": round(precision_down * 100.0, 2)},
        "recall": {"up": round(recall_up * 100.0, 2),
                   "down": round(recall_down * 100.0, 2)},
        "prediction_counts": {"up": sum(predictions), "down": total - sum(predictions)},
        "confusion_matrix": {"true_up_pred_up": tp, "true_up_pred_down": fn,
                             "true_down_pred_up": fp, "true_down_pred_down": tn},
        "class_counts": {"up": sum(labels), "down": total - sum(labels)},
    }



def _walk_forward_evaluate(rows, labels, decision_indices, candle_count, horizon):
    """Expanding-window checks on development history; final holdout stays untouched."""
    folds = []
    # Four sequential evaluation windows confined to the 70% development block.
    # Validation (70-85%) and final test (85-100%) remain untouched by this tuning aid.
    boundaries = [int(candle_count * x) for x in (0.30, 0.40, 0.50, 0.60, 0.70)]
    for fold_number, (train_end, test_end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        train_pos = [i for i, d in enumerate(decision_indices) if d < train_end - horizon]
        test_pos = [i for i, d in enumerate(decision_indices)
                    if train_end + horizon <= d < test_end - horizon]
        y_train = [labels[i] for i in train_pos]
        y_test = [labels[i] for i in test_pos]
        if len(train_pos) < MIN_ROWS_PER_SPLIT or len(test_pos) < MIN_ROWS_PER_SPLIT or len(set(y_train)) < 2:
            folds.append({"fold": fold_number, "status": "insufficient_data",
                          "train_samples": len(train_pos), "test_samples": len(test_pos)})
            continue
        train_rows = [rows[i] for i in train_pos]
        test_rows = [rows[i] for i in test_pos]
        means, scales = _fit_scaler(train_rows)
        train_x = _transform(train_rows, means, scales)
        test_x = _transform(test_rows, means, scales)
        weights = _fit_logistic(train_x, y_train)
        metrics = _score(test_x, y_test, weights)
        majority = 1 if sum(y_train) >= len(y_train) / 2 else 0
        baseline = sum(y == majority for y in y_test) / len(y_test) * 100.0
        folds.append({
            "fold": fold_number, "status": "complete",
            "training_end_candle_index": train_end,
            "test_end_candle_index_exclusive": test_end,
            "train_samples": len(train_pos), "test_samples": len(test_pos),
            "metrics": metrics,
            "train_majority_baseline_accuracy_pct": round(baseline, 2),
            "accuracy_minus_baseline_pct_points": round(metrics["accuracy_pct"] - baseline, 2),
            "scaler_fit_on": "this fold's training block only",
        })
    completed = [fold for fold in folds if fold["status"] == "complete"]
    return {
        "method": "expanding training window with sequential purged test windows",
        "completed_folds": len(completed),
        "total_folds": len(folds),
        "mean_fold_accuracy_pct": round(sum(x["metrics"]["accuracy_pct"] for x in completed) / len(completed), 2) if completed else None,
        "mean_fold_balanced_accuracy_pct": round(sum(x["metrics"]["balanced_accuracy_pct"] for x in completed) / len(completed), 2) if completed else None,
        "folds": folds,
        "note": "These development folds are diagnostic; the separate untouched test block remains the final holdout.",
    }


def _confidence_coverage(rows, labels, weights, thresholds=(0.55, 0.60, 0.65, 0.70)):
    """Evaluate only predictions whose probability is far enough from 0.5."""
    probabilities = [
        _sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], row)))
        for row in rows
    ]
    reports = []
    total = len(labels)
    for threshold in thresholds:
        selected = [(p, y) for p, y in zip(probabilities, labels)
                    if p >= threshold or p <= 1.0 - threshold]
        correct = sum((p >= 0.5) == bool(y) for p, y in selected)
        count = len(selected)
        reports.append({
            "probability_threshold": threshold,
            "selected_samples": count,
            "coverage_pct": round(count / total * 100.0, 2) if total else 0.0,
            "abstention_pct": round((total - count) / total * 100.0, 2) if total else 100.0,
            "accuracy_pct": round(correct / count * 100.0, 2) if count else None,
            "up_predictions": sum(p >= threshold for p, _ in selected),
            "down_predictions": sum(p <= 1.0 - threshold for p, _ in selected),
        })
    calibration_bins = []
    for lower, upper in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6),
                         (0.6, 0.8), (0.8, 1.0000001)):
        bucket = [(p, y) for p, y in zip(probabilities, labels)
                  if lower <= p < upper]
        calibration_bins.append({
            "probability_range": [lower, min(upper, 1.0)],
            "samples": len(bucket),
            "mean_predicted_up_probability": round(sum(p for p, _ in bucket) / len(bucket), 4) if bucket else None,
            "observed_up_rate": round(sum(y for _, y in bucket) / len(bucket), 4) if bucket else None,
        })
    brier_score = (sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / total
                   if total else None)
    # Expected calibration error weights each bin's probability/rate gap by its share.
    populated_bins = [bucket for bucket in calibration_bins if bucket["samples"]]
    expected_calibration_error = (
        sum(bucket["samples"] / total * abs(
            bucket["mean_predicted_up_probability"] - bucket["observed_up_rate"]
        ) for bucket in populated_bins) if total else None
    )
    max_calibration_error = (
        max(abs(bucket["mean_predicted_up_probability"] - bucket["observed_up_rate"])
            for bucket in populated_bins) if populated_bins else None
    )
    return {
        "method": "symmetric model-probability threshold; lower-probability predictions abstain",
        "total_test_samples": total,
        "thresholds": reports,
        "brier_score": round(brier_score, 6) if brier_score is not None else None,
        "expected_calibration_error": round(expected_calibration_error, 6) if expected_calibration_error is not None else None,
        "max_calibration_error": round(max_calibration_error, 6) if max_calibration_error is not None else None,
        "calibration_bins": calibration_bins,
        "warning": "These are uncalibrated model probabilities, not proven confidence levels. Higher thresholds reduce coverage and do not guarantee higher future accuracy.",
    }

def evaluate_logistic_research(candles, horizon=5, min_move_pct=0.0):
    """Train on an early block and report later validation and test blocks.

    min_move_pct is a configurable neutral-zone filter in percentage points;
    it is not a substitute for broker spread, commission or slippage modelling.
    """
    if not isinstance(candles, list):
        raise ValueError("candles must be a list")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 1 and 100")
    if isinstance(min_move_pct, bool) or not isinstance(min_move_pct, (int, float)) or not math.isfinite(min_move_pct) or not 0 <= min_move_pct <= 10:
        raise ValueError("min_move_pct must be a finite number between 0 and 10")
    if len(candles) < MIN_CANDLES:
        return {
            "status": "insufficient_data", "candle_count": len(candles),
            "minimum_candles": MIN_CANDLES, "ai_trained": False,
            "message": "Fresh, larger candle history is required; no model was trained.",
        }
    normalized = []
    previous_time = None
    for row in candles:
        try:
            item = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            timestamp = int(row["time"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Each candle needs valid time and OHLC values.")
        if not all(math.isfinite(v) and v > 0 for v in item.values()):
            raise ValueError("Candle prices must be finite positive numbers.")
        if item["high"] < max(item["open"], item["close"], item["low"]) or item["low"] > min(item["open"], item["close"], item["high"]):
            raise ValueError("Candle OHLC values are inconsistent.")
        if previous_time is not None and timestamp <= previous_time:
            raise ValueError("Candles must be strictly ordered by increasing time.")
        previous_time = timestamp
        normalized.append({"time": timestamp, **item})

    rows, labels, decision_indices = [], [], []
    excluded_small_moves = 0
    for index in range(30, len(normalized) - horizon):
        entry = normalized[index + 1]["open"]
        exit_price = normalized[index + horizon]["close"]
        move_pct = (exit_price / entry - 1.0) * 100.0
        if abs(move_pct) <= float(min_move_pct):
            excluded_small_moves += 1
            continue
        rows.append(_features(normalized, index))
        labels.append(1 if exit_price > entry else 0)
        decision_indices.append(index)

    total = len(rows)
    # Split on original candle indices, not compressed sample positions. This
    # keeps the purge valid even when flat outcomes were excluded.
    train_boundary = int(len(normalized) * 0.70)
    validation_boundary = int(len(normalized) * 0.85)
    train_positions = [i for i, decision in enumerate(decision_indices)
                       if decision < train_boundary - horizon]
    validation_positions = [i for i, decision in enumerate(decision_indices)
                            if train_boundary + horizon <= decision < validation_boundary - horizon]
    test_positions = [i for i, decision in enumerate(decision_indices)
                      if decision >= validation_boundary + horizon]
    train_rows, train_labels = [rows[i] for i in train_positions], [labels[i] for i in train_positions]
    validation_rows, validation_labels = [rows[i] for i in validation_positions], [labels[i] for i in validation_positions]
    test_rows, test_labels = [rows[i] for i in test_positions], [labels[i] for i in test_positions]
    if min(len(train_rows), len(validation_rows), len(test_rows)) < MIN_ROWS_PER_SPLIT:
        return {
            "status": "insufficient_data", "candle_count": len(normalized),
            "eligible_samples": total, "split_samples": {
                "train": len(train_rows), "validation": len(validation_rows), "test": len(test_rows)
            }, "minimum_samples_per_split": MIN_ROWS_PER_SPLIT,
            "ai_trained": False, "message": "Not enough purged samples in every chronological split.",
        }
    if len(set(train_labels)) < 2:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "Training block contains only one direction; no model was trained."}

    means, scales = _fit_scaler(train_rows)
    train_x = _transform(train_rows, means, scales)
    validation_x = _transform(validation_rows, means, scales)
    test_x = _transform(test_rows, means, scales)
    weights, fit_diagnostics = _fit_logistic(train_x, train_labels, return_diagnostics=True)
    probability_diagnostics = {
        "train": _probability_summary(train_x, weights),
        "validation": _probability_summary(validation_x, weights),
        "untouched_test": _probability_summary(test_x, weights),
        "note": "Probability summaries are descriptive only; validation and test were not used to fit or tune this candidate.",
    }
    train_metrics = _score(train_x, train_labels, weights)
    validation_metrics = _score(validation_x, validation_labels, weights)
    test_metrics = _score(test_x, test_labels, weights)
    confidence_coverage = _confidence_coverage(test_x, test_labels, weights)
    majority = 1 if sum(train_labels) >= len(train_labels) / 2 else 0
    baseline_accuracy = sum(y == majority for y in test_labels) / len(test_labels) * 100.0
    walk_forward = _walk_forward_evaluate(rows, labels, decision_indices, len(normalized), horizon)
    return {
        "status": "complete",
        "walk_forward": walk_forward,
        "model_type": "logistic_regression_research_candidate",
        "candidate_model_trained": True,
        "ai_trained": False,
        "production_model_persisted": False,
        "feature_names": list(FEATURE_NAMES),
        "horizon_candles": horizon,
        "neutral_zone_min_move_pct": round(float(min_move_pct), 6),
        "excluded_small_move_outcomes": excluded_small_moves,
        "eligible_samples": total,
        "split_samples": {"train": len(train_rows), "validation": len(validation_rows), "test": len(test_rows)},
        "purge_candles_each_boundary": horizon,
        "scaler_fit_on": "training block only",
        "decision_features_use_data_through": "decision candle close only",
        "label": "next candle open to horizon candle close; UP or DOWN; flat outcomes excluded",
        "train": train_metrics,
        "validation": validation_metrics,
        "untouched_test": test_metrics,
        "confidence_coverage": confidence_coverage,
        "fit_diagnostics": fit_diagnostics,
        "probability_diagnostics": probability_diagnostics,
        "test_majority_baseline_accuracy_pct": round(baseline_accuracy, 2),
        "test_accuracy_minus_baseline_pct_points": round(test_metrics["accuracy_pct"] - baseline_accuracy, 2),
        "limitations": ["Walk-forward folds are development diagnostics, not proof of future performance.",
                        "The final chronological test is one historical period and may not represent future regimes.",
                        "No spreads, commissions, slippage or swaps are included.",
                        "This research candidate is not loaded by the live analysis endpoint."],
        "read_only": True,
        "execution_enabled": False,
    }
