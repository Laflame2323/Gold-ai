"""Gradient-boosting research candidate for multi-timeframe Gold direction.

Uses completed H4/H1/M30/M15 features, chronological purged splits, training-only
class weights, validation-only hyperparameter selection, and one untouched test.
This is research-only and never persists or executes a model.
"""
from __future__ import annotations

from multitimeframe_features import build_multitimeframe_features
from research_ml import MIN_ROWS_PER_SPLIT


def _metrics(y_true, y_pred):
    total = len(y_true)
    tp = sum(p == 1 and y == 1 for p, y in zip(y_pred, y_true))
    tn = sum(p == 0 and y == 0 for p, y in zip(y_pred, y_true))
    fp = sum(p == 1 and y == 0 for p, y in zip(y_pred, y_true))
    fn = sum(p == 0 and y == 1 for p, y in zip(y_pred, y_true))
    up_recall = tp / (tp + fn) if tp + fn else 0.0
    down_recall = tn / (tn + fp) if tn + fp else 0.0
    return {
        "samples": total,
        "accuracy_pct": round((tp + tn) / total * 100, 2) if total else None,
        "balanced_accuracy_pct": round((up_recall + down_recall) * 50, 2),
        "precision": {
            "up": round(tp / (tp + fp) * 100, 2) if tp + fp else 0.0,
            "down": round(tn / (tn + fn) * 100, 2) if tn + fn else 0.0,
        },
        "recall": {"up": round(up_recall * 100, 2), "down": round(down_recall * 100, 2)},
        "prediction_counts": {"up": sum(y_pred), "down": total - sum(y_pred)},
        "confusion_matrix": {
            "true_up_pred_up": tp, "true_up_pred_down": fn,
            "true_down_pred_up": fp, "true_down_pred_down": tn,
        },
        "class_counts": {"up": sum(y_true), "down": total - sum(y_true)},
    }


def _class_weights(labels):
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        raise ValueError("Training block must contain both directions.")
    return [len(labels) / (2 * (2 * positives if y else 2 * negatives)) for y in labels]


def evaluate_gradient_boosting(candles_by_timeframe, horizon=5, min_move_pct=0.0):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier

    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 1 and 100")
    if isinstance(min_move_pct, bool) or not isinstance(min_move_pct, (int, float)) or not 0 <= min_move_pct <= 10:
        raise ValueError("min_move_pct must be between 0 and 10")

    base = candles_by_timeframe.get("H1")
    if not isinstance(base, list) or len(base) < 1000:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "At least 1,000 H1 candles are required."}

    aligned = build_multitimeframe_features(
        candles_by_timeframe, base_timeframe="H1",
        timeframes=("H4", "H1", "M30", "M15"),
    )
    base_by_decision = {
        int(c["time"]) + 3600: (i, c) for i, c in enumerate(base)
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

    if not decision_indices:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "No aligned samples are available."}
    start, end = min(decision_indices), max(decision_indices) + 1
    span = end - start
    train_edge = start + int(span * .70)
    validation_edge = start + int(span * .85)
    train_pos = [i for i, d in enumerate(decision_indices) if d < train_edge - horizon]
    val_pos = [i for i, d in enumerate(decision_indices)
               if train_edge + horizon <= d < validation_edge - horizon]
    test_pos = [i for i, d in enumerate(decision_indices) if d >= validation_edge + horizon]
    sizes = {"train": len(train_pos), "validation": len(val_pos), "test": len(test_pos)}
    if min(sizes.values()) < MIN_ROWS_PER_SPLIT:
        return {"status": "insufficient_data", "ai_trained": False,
                "eligible_samples": len(rows), "split_samples": sizes,
                "minimum_samples_per_split": MIN_ROWS_PER_SPLIT}
    y_train = np.asarray([labels[i] for i in train_pos], dtype=np.int64)
    y_val = np.asarray([labels[i] for i in val_pos], dtype=np.int64)
    y_test = np.asarray([labels[i] for i in test_pos], dtype=np.int64)
    if len(np.unique(y_train)) < 2:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "Training block contains only one direction."}
    x = np.asarray(rows, dtype=np.float64)
    x_train, x_val, x_test = x[train_pos], x[val_pos], x[test_pos]
    sample_weights = np.asarray(_class_weights(y_train.tolist()), dtype=np.float64)

    # Small, predeclared grid: validation selects; test is never used for tuning.
    candidates = []
    for leaves in (7, 15, 31):
        for rate in (0.03, 0.07):
            model = HistGradientBoostingClassifier(
                max_iter=200, learning_rate=rate, max_leaf_nodes=leaves,
                l2_regularization=1.0, early_stopping=False, random_state=17,
            )
            model.fit(x_train, y_train, sample_weight=sample_weights)
            val_pred = model.predict(x_val)
            score = _metrics(y_val.tolist(), val_pred.astype(int).tolist())
            candidates.append({
                "max_leaf_nodes": leaves, "learning_rate": rate,
                "validation": score, "model": model,
            })
    best = max(candidates, key=lambda c: (
        c["validation"]["balanced_accuracy_pct"], c["validation"]["accuracy_pct"],
        -c["max_leaf_nodes"], -c["learning_rate"],
    ))
    final_model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=best["learning_rate"],
        max_leaf_nodes=best["max_leaf_nodes"], l2_regularization=1.0,
        early_stopping=False, random_state=17,
    )
    final_model.fit(x_train, y_train, sample_weight=sample_weights)

    train_pred = final_model.predict(x_train).astype(int).tolist()
    val_pred = final_model.predict(x_val).astype(int).tolist()
    test_pred = final_model.predict(x_test).astype(int).tolist()
    test_prob = final_model.predict_proba(x_test)[:, 1]
    test_confidence = np.maximum(test_prob, 1.0 - test_prob)
    coverage = []
    for threshold in (0.55, 0.60, 0.65, 0.70, 0.75):
        selected = test_confidence >= threshold
        count = int(np.sum(selected))
        coverage.append({
            "probability_threshold": threshold, "selected_samples": count,
            "coverage_pct": round(count / len(test_pos) * 100, 2),
            "accuracy_pct": round(float(np.mean(np.asarray(test_pred)[selected] == y_test[selected])) * 100, 2) if count else None,
        })
    train_majority = int(np.mean(y_train) >= .5)
    baseline = float(np.mean(y_test == train_majority) * 100)
    return {
        "status": "complete",
        "model_type": "validation_selected_hist_gradient_boosting_research_candidate",
        "candidate_model_trained": True, "ai_trained": False,
        "production_model_persisted": False,
        "symbol": "XAUUSDm", "timeframes": aligned["timeframes"],
        "feature_count": len(aligned["feature_names"]),
        "feature_names": aligned["feature_names"],
        "horizon_candles": horizon, "neutral_zone_min_move_pct": float(min_move_pct),
        "excluded_small_move_outcomes": excluded,
        "eligible_samples": len(rows), "split_samples": sizes,
        "purge_candles_each_boundary": horizon,
        "selection_rule": "highest validation balanced accuracy; accuracy breaks ties; smaller trees break remaining ties",
        "validation_candidates": [
            {k: v for k, v in c.items() if k != "model"} for c in candidates
        ],
        "selected_parameters": {
            "max_leaf_nodes": best["max_leaf_nodes"],
            "learning_rate": best["learning_rate"],
            "max_iter": 200, "class_weighting": "inverse_frequency_sample_weights",
        },
        "train": _metrics(y_train.tolist(), train_pred),
        "validation": _metrics(y_val.tolist(), val_pred),
        "untouched_test": _metrics(y_test.tolist(), test_pred),
        "test_majority_baseline_accuracy_pct": round(baseline, 2),
        "test_accuracy_minus_baseline_pct_points": round(
            _metrics(y_test.tolist(), test_pred)["accuracy_pct"] - baseline, 2
        ),
        "confidence_coverage": {
            "method": "abstain when max class probability is below threshold",
            "total_test_samples": len(test_pos), "thresholds": coverage,
            "warning": "Probabilities are not calibrated confidence estimates.",
        },
        "research_only": True, "read_only": True, "execution_enabled": False,
        "accuracy_is_live": False,
        "limitations": [
            "Experimental gradient-boosting candidate; no production persistence or execution.",
            "Fixed-horizon labels; no spread, commission, slippage or swap costs.",
            "A fresh future period is required after model selection.",
        ],
    }
