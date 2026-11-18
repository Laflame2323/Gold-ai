"""ATR triple-barrier and rule-side meta-label research evaluator.

All features are available at the completed H1 decision close. Entries use the
next H1 open. Labels scan only subsequent completed H1 OHLC bars. Ambiguous
same-bar touches are conservatively neutral. This module is read-only research.
"""
from __future__ import annotations

import math

from multitimeframe_features import build_multitimeframe_features
from research_ml import MIN_ROWS_PER_SPLIT


def _atr(candles, period=14):
    values = []
    previous_close = None
    for candle in candles:
        high, low, close = (float(candle[k]) for k in ("high", "low", "close"))
        tr = high - low if previous_close is None else max(
            high - low, abs(high - previous_close), abs(low - previous_close)
        )
        values.append(tr)
        previous_close = close
    result = [None] * len(candles)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    for i in range(period, len(values)):
        current = ((period - 1) * current + values[i]) / period
        result[i] = current
    return result


def _metrics(y_true, y_pred):
    total = len(y_true)
    if not total:
        return {"samples": 0, "accuracy_pct": None, "balanced_accuracy_pct": None}
    classes = sorted(set(y_true) | set(y_pred))
    recalls = []
    per_class = {}
    for label in classes:
        actual = sum(y == label for y in y_true)
        correct = sum(y == label and p == label for y, p in zip(y_true, y_pred))
        predicted = sum(p == label for p in y_pred)
        recall = correct / actual if actual else 0.0
        recalls.append(recall)
        per_class[str(label)] = {
            "actual": actual, "predicted": predicted,
            "recall_pct": round(recall * 100, 2),
        }
    return {
        "samples": total,
        "accuracy_pct": round(sum(y == p for y, p in zip(y_true, y_pred)) / total * 100, 2),
        "balanced_accuracy_pct": round(sum(recalls) / len(recalls) * 100, 2),
        "classes": per_class,
    }


def _weights(labels):
    counts = {label: labels.count(label) for label in set(labels)}
    if len(counts) < 2:
        raise ValueError("Training labels must contain at least two classes.")
    total = len(labels)
    return [total / (len(counts) * counts[label]) for label in labels]


def _make_samples(candles_by_timeframe, horizon, pt_atr, sl_atr):
    import numpy as np

    base = candles_by_timeframe.get("H1")
    if not isinstance(base, list) or len(base) < 1000:
        return None, {"status": "insufficient_data", "ai_trained": False,
                      "message": "At least 1,000 H1 candles are required."}
    aligned = build_multitimeframe_features(
        candles_by_timeframe, base_timeframe="H1",
        timeframes=("H4", "H1", "M30", "M15"),
    )
    by_decision = {int(c["time"]) + 3600: i for i, c in enumerate(base)}
    atr = _atr(base, 14)
    rows, outcomes, sides, decisions, label_end_indices = [], [], [], [], []
    counts = {"profit_target": 0, "stop_loss": 0, "vertical_or_no_touch": 0,
              "ambiguous_same_bar": 0, "missing_atr": 0}
    for item in aligned["rows"]:
        i = by_decision.get(item["decision_time"])
        if i is None or i + 1 >= len(base) or i + horizon >= len(base):
            continue
        if atr[i] is None or not math.isfinite(atr[i]) or atr[i] <= 0:
            counts["missing_atr"] += 1
            continue
        entry = float(base[i + 1]["open"])
        upper = entry + pt_atr * atr[i]
        lower = entry - sl_atr * atr[i]
        outcome, end_index = 0, i + horizon
        for j in range(i + 1, min(i + horizon, len(base) - 1) + 1):
            hit_up = float(base[j]["high"]) >= upper
            hit_down = float(base[j]["low"]) <= lower
            if hit_up and hit_down:
                counts["ambiguous_same_bar"] += 1
                outcome, end_index = 0, j
                break
            if hit_up:
                outcome, end_index = 1, j
                counts["profit_target"] += 1
                break
            if hit_down:
                outcome, end_index = -1, j
                counts["stop_loss"] += 1
                break
        else:
            counts["vertical_or_no_touch"] += 1
        features = item["features"]
        # H1 is the second timeframe block; EMA10 gap is its fourth feature.
        h1_ema_gap_10 = float(features[12])
        if not math.isfinite(h1_ema_gap_10) or h1_ema_gap_10 == 0:
            continue
        side = 1 if h1_ema_gap_10 > 0 else -1
        rows.append(features)
        outcomes.append(outcome)
        sides.append(side)
        decisions.append(i)
        label_end_indices.append(end_index)
    if not rows:
        return None, {"status": "insufficient_data", "ai_trained": False,
                      "message": "No eligible triple-barrier events were aligned."}
    return {
        "x": np.asarray(rows, dtype=np.float64),
        "outcomes": outcomes, "sides": sides, "decisions": decisions,
        "label_ends": label_end_indices, "aligned": aligned, "counts": counts,
        "base_count": len(base),
    }, None


def evaluate_triple_barrier_meta(candles_by_timeframe, horizon=12,
                                 pt_atr=1.5, sl_atr=1.0):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier

    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 2 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 2 and 100")
    for name, value in (("pt_atr", pt_atr), ("sl_atr", sl_atr)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.1 <= value <= 10:
            raise ValueError(f"{name} must be between 0.1 and 10")
    sample, error = _make_samples(candles_by_timeframe, horizon, float(pt_atr), float(sl_atr))
    if error:
        return error

    decisions = sample["decisions"]
    outcomes, sides = sample["outcomes"], sample["sides"]
    x = sample["x"]
    start, end = min(decisions), max(decisions) + 1
    span = end - start
    train_edge = start + int(span * .70)
    validation_edge = start + int(span * .85)
    train = [k for k, d in enumerate(decisions)
             if sample["label_ends"][k] < train_edge]
    validation = [k for k, d in enumerate(decisions)
                  if d >= train_edge and sample["label_ends"][k] < validation_edge]
    test = [k for k, d in enumerate(decisions) if d >= validation_edge]
    sizes = {"train": len(train), "validation": len(validation), "test": len(test)}
    if min(sizes.values()) < MIN_ROWS_PER_SPLIT:
        return {"status": "insufficient_data", "ai_trained": False,
                "eligible_samples": len(decisions), "split_samples": sizes,
                "minimum_samples_per_split": MIN_ROWS_PER_SPLIT}

    # A deterministic trend-side primary signal; the ML meta-model only learns
    # whether to accept/pass that side. Neutral and opposing barrier outcomes are failures.
    meta_y = [int(outcomes[k] == sides[k]) for k in range(len(outcomes))]
    train_y = [meta_y[k] for k in train]
    if len(set(train_y)) < 2:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "Training meta-labels contain only one class.",
                "split_samples": sizes}
    weights = np.asarray(_weights(train_y), dtype=np.float64)
    candidates = []
    for leaves in (7, 15, 31):
        for rate in (0.03, 0.07):
            model = HistGradientBoostingClassifier(
                max_iter=200, learning_rate=rate, max_leaf_nodes=leaves,
                l2_regularization=1.0, early_stopping=False, random_state=23,
            )
            model.fit(x[train], np.asarray(train_y), sample_weight=weights)
            pred = model.predict(x[validation]).astype(int).tolist()
            score = _metrics([meta_y[k] for k in validation], pred)
            candidates.append({"max_leaf_nodes": leaves, "learning_rate": rate,
                               "validation": score, "model": model})
    best = max(candidates, key=lambda c: (
        c["validation"]["balanced_accuracy_pct"], c["validation"]["accuracy_pct"],
        -c["max_leaf_nodes"], -c["learning_rate"],
    ))
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=best["learning_rate"],
        max_leaf_nodes=best["max_leaf_nodes"], l2_regularization=1.0,
        early_stopping=False, random_state=23,
    )
    model.fit(x[train], np.asarray(train_y), sample_weight=weights)
    test_prob = model.predict_proba(x[test])[:, list(model.classes_).index(1)]
    test_meta_pred = model.predict(x[test]).astype(int).tolist()
    primary_correct = [meta_y[k] for k in test]
    primary_accuracy = sum(primary_correct) / len(primary_correct) * 100
    thresholds = []
    for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
        selected = test_prob >= threshold
        n = int(np.sum(selected))
        wins = sum(primary_correct[i] for i, keep in enumerate(selected) if keep)
        thresholds.append({
            "meta_probability_threshold": threshold,
            "accepted_trades": n,
            "coverage_pct": round(n / len(test) * 100, 2),
            "accepted_trade_win_rate_pct": round(wins / n * 100, 2) if n else None,
        })
    y_test = [meta_y[k] for k in test]
    return {
        "status": "complete",
        "model_type": "atr_triple_barrier_rule_side_meta_label_hist_gradient_boosting",
        "candidate_model_trained": True, "ai_trained": False,
        "production_model_persisted": False,
        "eligible_samples": len(decisions), "split_samples": sizes,
        "barriers": {"profit_target_atr": float(pt_atr), "stop_loss_atr": float(sl_atr),
                     "vertical_horizon_h1_candles": horizon,
                     "same_bar_both_touched": "neutral_conservative"},
        "outcome_counts": sample["counts"],
        "triple_barrier_outcomes": {
            "upper_barrier_hits": outcomes.count(1),
            "lower_barrier_hits": outcomes.count(-1),
            "vertical_or_ambiguous": outcomes.count(0),
        },
        "primary_rule": "side = sign of completed H1 EMA10 gap",
        "primary_test_meta_label_win_rate_pct": round(primary_accuracy, 2),
        "meta_model_test": _metrics(y_test, test_meta_pred),
        "test_majority_baseline_accuracy_pct": round(
            max(y_test.count(0), y_test.count(1)) / len(y_test) * 100, 2),
        "confidence_coverage": thresholds,
        "validation_candidates": [
            {k: v for k, v in c.items() if k != "model"} for c in candidates
        ],
        "selected_parameters": {"max_leaf_nodes": best["max_leaf_nodes"],
                                "learning_rate": best["learning_rate"],
                                "max_iter": 200, "class_weighting": "inverse_frequency"},
        "feature_names": sample["aligned"]["feature_names"],
        "research_only": True, "read_only": True, "execution_enabled": False,
        "accuracy_is_live": False,
        "limitations": [
            "Rule-side meta-labeling only; primary side is completed H1 EMA10 trend.",
            "No spread, commission, slippage or swap costs are included.",
            "Same-bar touches of both horizontal barriers are labeled neutral.",
            "Test is chronological but is not a newly collected future period.",
            "Probabilities are not calibrated.",
        ],
    }
