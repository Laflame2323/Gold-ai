"""ATR triple-barrier rule-side meta-label evaluator; read-only research."""
from __future__ import annotations

import math
import numpy as np
from multitimeframe_features import build_multitimeframe_features
from research_ml import MIN_ROWS_PER_SPLIT
from causal_smc_features import FEATURE_NAMES as SMC_FEATURE_NAMES, causal_smc_features


BASE_INTERVALS = {"H1": 3600, "M30": 1800}


def _atr(candles, period=14):
    values, previous = [], None
    for candle in candles:
        high, low, close = (float(candle[k]) for k in ("high", "low", "close"))
        values.append(high - low if previous is None else
                      max(high - low, abs(high - previous), abs(low - previous)))
        previous = close
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
    recalls, classes = [], {}
    for label in sorted(set(y_true)):
        actual = sum(y == label for y in y_true)
        correct = sum(y == label and p == label for y, p in zip(y_true, y_pred))
        predicted = sum(p == label for p in y_pred)
        recall = correct / actual
        recalls.append(recall)
        classes[str(label)] = {
            "actual": actual, "predicted": predicted,
            "recall_pct": round(recall * 100, 2),
        }
    return {
        "samples": total,
        "accuracy_pct": round(sum(y == p for y, p in zip(y_true, y_pred)) / total * 100, 2),
        "balanced_accuracy_pct": round(sum(recalls) / len(recalls) * 100, 2),
        "classes": classes,
    }


def _weights(labels):
    counts = {label: labels.count(label) for label in set(labels)}
    if len(counts) < 2:
        raise ValueError("Training labels must contain at least two classes.")
    return [len(labels) / (len(counts) * counts[label]) for label in labels]


def _make_samples(candles_by_timeframe, horizon, pt_atr, sl_atr, base_timeframe):
    base = candles_by_timeframe.get(base_timeframe)
    if not isinstance(base, list) or len(base) < 1000:
        return None, {"status": "insufficient_data", "ai_trained": False,
                      "message": f"At least 1,000 {base_timeframe} candles are required."}
    aligned = build_multitimeframe_features(
        candles_by_timeframe, base_timeframe=base_timeframe,
        timeframes=("H4", "H1", "M30", "M15"),
    )
    by_decision = {
        int(c["time"]) + BASE_INTERVALS[base_timeframe]: i
        for i, c in enumerate(base)
    }
    atr = _atr(base, 14)
    rows, outcomes, sides, decisions, label_ends = [], [], [], [], []
    counts = {"profit_target": 0, "stop_loss": 0, "vertical_or_no_touch": 0,
              "ambiguous_same_bar": 0, "missing_atr": 0}
    side_index = aligned["feature_names"].index(
        f"{base_timeframe.lower()}_ema_gap_10"
    )
    for item in aligned["rows"]:
        i = by_decision.get(item["decision_time"])
        if i is None or i + horizon >= len(base):
            continue
        if atr[i] is None or not math.isfinite(atr[i]) or atr[i] <= 0:
            counts["missing_atr"] += 1
            continue
        trend_gap = float(item["features"][side_index])
        if not math.isfinite(trend_gap) or trend_gap == 0:
            continue
        side = 1 if trend_gap > 0 else -1
        entry = float(base[i + 1]["open"])
        upper, lower = entry + pt_atr * atr[i], entry - sl_atr * atr[i]
        outcome, end_index = 0, i + horizon
        for j in range(i + 1, i + horizon + 1):
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
        rows.append(item["features"] + causal_smc_features(base, i, atr[i]))
        outcomes.append(outcome)
        sides.append(side)
        decisions.append(i)
        label_ends.append(end_index)
    if not rows:
        return None, {"status": "insufficient_data", "ai_trained": False,
                      "message": "No eligible triple-barrier events were aligned."}
    return {
        "x": np.asarray(rows, dtype=np.float64), "outcomes": outcomes,
        "sides": sides, "decisions": decisions, "label_ends": label_ends,
        "aligned": aligned, "counts": counts,
    }, None


def evaluate_triple_barrier_meta(candles_by_timeframe, horizon=24,
                                 pt_atr=1.5, sl_atr=1.0, base_timeframe="M30"):
    from sklearn.ensemble import HistGradientBoostingClassifier

    if base_timeframe not in BASE_INTERVALS:
        raise ValueError("base_timeframe must be H1 or M30")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 2 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 2 and 100")
    for name, value in (("pt_atr", pt_atr), ("sl_atr", sl_atr)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.1 <= value <= 10:
            raise ValueError(f"{name} must be between 0.1 and 10")
    sample, error = _make_samples(
        candles_by_timeframe, horizon, float(pt_atr), float(sl_atr), base_timeframe
    )
    if error:
        return error

    decisions = sample["decisions"]
    outcomes, sides, x = sample["outcomes"], sample["sides"], sample["x"]
    start, end = min(decisions), max(decisions) + 1
    span = end - start
    train_edge, validation_edge = start + int(span * .70), start + int(span * .85)
    train = [k for k in range(len(decisions)) if sample["label_ends"][k] < train_edge]
    validation = [k for k, d in enumerate(decisions)
                  if d >= train_edge and sample["label_ends"][k] < validation_edge]
    test = [k for k, d in enumerate(decisions) if d >= validation_edge]
    sizes = {"train": len(train), "validation": len(validation), "test": len(test)}
    if min(sizes.values()) < MIN_ROWS_PER_SPLIT:
        return {"status": "insufficient_data", "ai_trained": False,
                "eligible_samples": len(decisions), "split_samples": sizes,
                "minimum_samples_per_split": MIN_ROWS_PER_SPLIT}

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
            candidates.append({
                "max_leaf_nodes": leaves, "learning_rate": rate,
                "validation": _metrics([meta_y[k] for k in validation], pred),
            })
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
    test_pred = model.predict(x[test]).astype(int).tolist()
    test_y = [meta_y[k] for k in test]
    thresholds = []
    for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
        selected = test_prob >= threshold
        count = int(np.sum(selected))
        wins = sum(test_y[i] for i, keep in enumerate(selected) if keep)
        thresholds.append({
            "meta_probability_threshold": threshold,
            "accepted_trades": count,
            "coverage_pct": round(count / len(test) * 100, 2),
            "accepted_trade_win_rate_pct": round(wins / count * 100, 2) if count else None,
        })
    primary_accuracy = sum(test_y) / len(test_y) * 100
    return {
        "status": "complete",
        "model_type": f"atr_triple_barrier_{base_timeframe.lower()}_causal_smc_meta_label_hist_gradient_boosting",
        "base_timeframe": base_timeframe,
        "candidate_model_trained": True, "ai_trained": False,
        "production_model_persisted": False,
        "eligible_samples": len(decisions), "split_samples": sizes,
        "barriers": {"profit_target_atr": float(pt_atr), "stop_loss_atr": float(sl_atr),
                     "vertical_horizon_candles": horizon, "base_timeframe": base_timeframe,
                     "same_bar_both_touched": "neutral_conservative"},
        "outcome_counts": sample["counts"],
        "triple_barrier_outcomes": {
            "upper_barrier_hits": outcomes.count(1),
            "lower_barrier_hits": outcomes.count(-1),
            "vertical_or_ambiguous": outcomes.count(0),
        },
        "primary_rule": f"side = sign of completed {base_timeframe} EMA10 gap",
        "primary_test_meta_label_win_rate_pct": round(primary_accuracy, 2),
        "meta_model_test": _metrics(test_y, test_pred),
        "test_majority_baseline_accuracy_pct": round(
            max(test_y.count(0), test_y.count(1)) / len(test_y) * 100, 2),
        "confidence_coverage": thresholds,
        "validation_candidates": candidates,
        "selected_parameters": {"max_leaf_nodes": best["max_leaf_nodes"],
                                "learning_rate": best["learning_rate"],
                                "max_iter": 200, "class_weighting": "inverse_frequency"},
        "feature_names": sample["aligned"]["feature_names"] + SMC_FEATURE_NAMES,
        "feature_groups": {"existing_multi_timeframe": len(sample["aligned"]["feature_names"]),
                           "causal_smc_price_action": len(SMC_FEATURE_NAMES)},
        "research_only": True, "read_only": True, "execution_enabled": False,
        "accuracy_is_live": False,
        "limitations": [
            f"Rule-side meta-labeling only; primary side is completed {base_timeframe} EMA10 trend.",
            "SMC features are causal price-action proxies; they do not establish institutional order flow.",
            "No spread, commission, slippage or swap costs are included.",
            "Same-bar touches of both horizontal barriers are labeled neutral.",
            "Test is chronological but is not a newly collected future period.",
            "Probabilities are not calibrated.",
        ],
    }
