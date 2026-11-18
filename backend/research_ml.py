"""Leakage-aware, pure-Python logistic-regression research evaluator.

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
    prefix = candles[:index + 1]
    closes = [float(row["close"]) for row in prefix]
    current = closes[-1]
    if current <= 0:
        raise ValueError("Candle prices must be positive.")
    def ret(period):
        return current / closes[-period - 1] - 1.0
    ema10, ema30 = _ema(closes, 10), _ema(closes, 30)
    row = prefix[-1]
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


def _fit_logistic(rows, labels, epochs=700, learning_rate=0.04, l2=0.01):
    weights = [0.0] * (len(FEATURE_NAMES) + 1)
    count = len(rows)
    for _ in range(epochs):
        gradients = [0.0] * len(weights)
        for row, label in zip(rows, labels):
            probability = _sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], row)))
            error = probability - label
            gradients[0] += error
            for j, value in enumerate(row, 1):
                gradients[j] += error * value
        weights[0] -= learning_rate * gradients[0] / count
        for j in range(1, len(weights)):
            weights[j] -= learning_rate * (gradients[j] / count + l2 * weights[j])
    return weights


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

def evaluate_logistic_research(candles, horizon=5):
    """Train on an early block and report later validation and test blocks."""
    if not isinstance(candles, list):
        raise ValueError("candles must be a list")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 1 and 100")
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
    for index in range(30, len(normalized) - horizon):
        entry = normalized[index + 1]["open"]
        exit_price = normalized[index + horizon]["close"]
        if exit_price == entry:
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
    weights = _fit_logistic(train_x, train_labels)
    train_metrics = _score(train_x, train_labels, weights)
    validation_metrics = _score(validation_x, validation_labels, weights)
    test_metrics = _score(test_x, test_labels, weights)
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
        "eligible_samples": total,
        "split_samples": {"train": len(train_rows), "validation": len(validation_rows), "test": len(test_rows)},
        "purge_candles_each_boundary": horizon,
        "scaler_fit_on": "training block only",
        "decision_features_use_data_through": "decision candle close only",
        "label": "next candle open to horizon candle close; UP or DOWN; flat outcomes excluded",
        "train": train_metrics,
        "validation": validation_metrics,
        "untouched_test": test_metrics,
        "test_majority_baseline_accuracy_pct": round(baseline_accuracy, 2),
        "test_accuracy_minus_baseline_pct_points": round(test_metrics["accuracy_pct"] - baseline_accuracy, 2),
        "limitations": ["Single chronological split; later walk-forward folds are still required.",
                        "No spreads, commissions, slippage or swaps are included.",
                        "This research candidate is not loaded by the live analysis endpoint."],
        "read_only": True,
        "execution_enabled": False,
    }
