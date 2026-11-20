"""Profit-aware, leakage-controlled triple-barrier meta-model research.

This module selects model family and confidence threshold on validation data
using risk-unit trade expectancy, then scores the selected configuration once
on a later untouched chronological test block. It never persists or executes
a model.
"""
from __future__ import annotations

import math
import numpy as np

from research_ml import MIN_ROWS_PER_SPLIT
from triple_barrier_research import _make_samples, _metrics


def _weights(labels):
    counts = {label: labels.count(label) for label in set(labels)}
    if len(counts) < 2:
        raise ValueError("Training labels must contain at least two classes.")
    return [len(labels) / (len(counts) * counts[label]) for label in labels]


def _trade_returns_r(outcomes, sides, indices, pt_atr, sl_atr, cost_atr):
    """Return per-setup net R; ambiguous/time-expired setups contribute zero gross R."""
    cost_r = cost_atr / sl_atr
    values = []
    for index in indices:
        outcome, side = outcomes[index], sides[index]
        if outcome == side:
            gross_r = pt_atr / sl_atr
        elif outcome == -side:
            gross_r = -1.0
        else:
            gross_r = 0.0
        values.append(gross_r - cost_r)
    return values


def _trade_metrics_r(values):
    count = len(values)
    if not count:
        return {
            "trades": 0, "coverage_pct": 0.0, "net_positive_rate_pct": None,
            "mean_net_r": None, "mean_net_r_lower_90_bound": None,
            "total_net_r": 0.0, "profit_factor": None,
            "max_drawdown_r": 0.0,
        }
    wins = sum(value > 0 for value in values)
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    mean_net_r = float(np.mean(values))
    # Empirical-Bernstein lower bound. Unlike a normal interval, it retains
    # a non-zero uncertainty penalty even when a small sample has identical returns.
    variance = float(np.var(values, ddof=1)) if count > 1 else 0.0
    value_range = max(values) - min(values)
    log_term = math.log(3.0 / 0.10)  # one-sided 90% confidence
    lower_bound = (
        mean_net_r
        - math.sqrt(2.0 * variance * log_term / count)
        - 3.0 * value_range * log_term / count
    )
    equity = peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": count,
        "net_positive_rate_pct": round(wins / count * 100, 2),
        "mean_net_r": round(mean_net_r, 4),
        "mean_net_r_lower_90_bound": round(lower_bound, 4),
        "total_net_r": round(float(sum(values)), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (
            None if gross_profit == 0 else "infinite"
        ),
        "max_drawdown_r": round(max_drawdown, 4),
    }


def _select_threshold(probabilities, outcomes, sides, rows, pt_atr, sl_atr, cost_atr):
    """Choose threshold only on validation; reject thin or non-positive samples."""
    candidates = []
    min_trades = max(20, int(math.ceil(len(rows) * 0.05)))
    for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90):
        selected = [rows[i] for i, probability in enumerate(probabilities)
                    if probability >= threshold]
        values = _trade_returns_r(
            outcomes, sides, selected, pt_atr, sl_atr, cost_atr
        )
        metrics = _trade_metrics_r(values)
        metrics["coverage_pct"] = round(len(selected) / len(rows) * 100, 2)
        candidates.append({"threshold": threshold, **metrics})
    eligible = [item for item in candidates
                if item["trades"] >= min_trades
                and item["mean_net_r_lower_90_bound"] is not None]
    best = max(eligible, key=lambda item: (
        item["mean_net_r_lower_90_bound"],
        item["mean_net_r"],
        item["trades"],
    )) if eligible else None
    if best is None or best["mean_net_r_lower_90_bound"] <= 0:
        return 1.01, candidates, False
    return best["threshold"], candidates, True


def evaluate_profit_aware_meta(candles_by_timeframe, horizon=24, pt_atr=1.5,
                               sl_atr=1.0, base_timeframe="M30",
                               round_trip_cost_atr=0.0):
    """Train ephemeral candidates and select by validation net expectancy in R."""
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if not math.isfinite(round_trip_cost_atr) or not 0 <= round_trip_cost_atr <= 2:
        raise ValueError("round_trip_cost_atr must be between 0 and 2.")
    sample, error = _make_samples(
        candles_by_timeframe, horizon, float(pt_atr), float(sl_atr), base_timeframe
    )
    if error:
        return error

    decisions = sample["decisions"]
    outcomes, sides, x = sample["outcomes"], sample["sides"], sample["x"]
    start, end = min(decisions), max(decisions) + 1
    span = end - start
    train_edge = start + int(span * 0.70)
    validation_edge = start + int(span * 0.85)

    # Purge any training/validation event whose label window reaches the next block.
    embargo_bars = horizon
    train = [i for i, decision in enumerate(decisions)
             if sample["label_ends"][i] < train_edge
             and decision < train_edge - embargo_bars]
    validation = [i for i, decision in enumerate(decisions)
                  if decision >= train_edge + embargo_bars
                  and sample["label_ends"][i] < validation_edge]
    test = [i for i, decision in enumerate(decisions)
            if decision >= validation_edge + embargo_bars]
    split_samples = {"train": len(train), "validation": len(validation), "test": len(test)}
    if min(split_samples.values()) < MIN_ROWS_PER_SPLIT:
        return {
            "status": "insufficient_data", "ai_trained": False,
            "eligible_samples": len(decisions), "split_samples": split_samples,
            "minimum_samples_per_split": MIN_ROWS_PER_SPLIT,
        }

    labels = [int(outcomes[i] == sides[i]) for i in range(len(outcomes))]
    train_y = [labels[i] for i in train]
    validation_y = [labels[i] for i in validation]
    test_y = [labels[i] for i in test]
    if len(set(train_y)) < 2:
        return {"status": "insufficient_data", "ai_trained": False,
                "message": "Training meta-labels contain only one class.",
                "split_samples": split_samples}

    weights = np.asarray(_weights(train_y), dtype=np.float64)
    specs = [
        {"family": "hist_gradient_boosting", "leaves": leaves, "rate": rate}
        for leaves in (7, 15) for rate in (0.03, 0.07)
    ] + [
        {"family": "extra_trees", "trees": 160, "depth": depth,
         "min_samples_leaf": 20, "max_features": 0.8}
        for depth in (8, 12)
    ] + [
        {"family": "logistic_regression", "C": strength}
        for strength in (0.1, 1.0, 10.0)
    ]

    evaluated = []
    for spec in specs:
        if spec["family"] == "hist_gradient_boosting":
            model = HistGradientBoostingClassifier(
                max_iter=200, learning_rate=spec["rate"],
                max_leaf_nodes=spec["leaves"], l2_regularization=1.0,
                early_stopping=False, random_state=23,
            )
            model.fit(x[train], np.asarray(train_y), sample_weight=weights)
        elif spec["family"] == "extra_trees":
            model = ExtraTreesClassifier(
                n_estimators=spec["trees"], max_depth=spec["depth"],
                min_samples_leaf=spec["min_samples_leaf"],
                max_features=spec["max_features"], n_jobs=1, random_state=23,
            )
            model.fit(x[train], np.asarray(train_y), sample_weight=weights)
        else:
            model = make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=spec["C"], max_iter=2000, solver="lbfgs",
                    class_weight=None, random_state=23,
                ),
            )
            model.fit(
                x[train], np.asarray(train_y),
                logisticregression__sample_weight=weights,
            )
        probabilities = model.predict_proba(x[validation])[:, list(model.classes_).index(1)]
        threshold, threshold_table, positive = _select_threshold(
            probabilities, outcomes, sides, validation, pt_atr, sl_atr,
            round_trip_cost_atr,
        )
        chosen = next((row for row in threshold_table if row["threshold"] == threshold), None)
        evaluated.append({
            "spec": spec, "model": model, "threshold": threshold,
            "threshold_table": threshold_table, "positive_validation_edge": positive,
            "validation_trade_metrics": chosen or {
                "trades": 0, "mean_net_r": None, "coverage_pct": 0.0,
                "profit_factor": None,
            },
            "validation_classification": _metrics(
                validation_y, model.predict(x[validation]).astype(int).tolist()
            ),
        })

    # Select only candidates with conservative positive validation expectancy.
    eligible_models = [
        item for item in evaluated
        if item["positive_validation_edge"]
        and item["validation_trade_metrics"]["mean_net_r_lower_90_bound"] is not None
        and item["validation_trade_metrics"]["mean_net_r_lower_90_bound"] > 0
    ]
    if not eligible_models:
        return {
            "status": "no_positive_validation_edge",
            "message": "No candidate passed the minimum-trade and conservative positive-expectancy checks.",
            "split_samples": split_samples,
            "candidate_models_evaluated": len(evaluated),
            "research_only": True,
            "read_only": True,
            "execution_enabled": False,
            "ai_trained": False,
            "model_persisted": False,
        }
    best = max(eligible_models, key=lambda item: (
        item["validation_trade_metrics"]["mean_net_r_lower_90_bound"],
        item["validation_trade_metrics"]["mean_net_r"],
        item["validation_trade_metrics"]["trades"],
    ))
    probabilities = best["model"].predict_proba(x[test])[:, list(best["model"].classes_).index(1)]
    accepted = [test[i] for i, probability in enumerate(probabilities)
                if probability >= best["threshold"]]
    test_returns = _trade_returns_r(
        outcomes, sides, accepted, pt_atr, sl_atr, round_trip_cost_atr
    )
    test_metrics = _trade_metrics_r(test_returns)
    test_metrics["coverage_pct"] = round(len(accepted) / len(test) * 100, 2)
    test_metrics["test_setups"] = len(test)
    test_metrics["classification"] = _metrics(
        test_y, best["model"].predict(x[test]).astype(int).tolist()
    )
    test_metrics["all_setup_win_rate_pct"] = round(sum(test_y) / len(test_y) * 100, 2)

    cost_sensitivity = []
    for cost in (0.0, 0.025, 0.05, 0.10, 0.20):
        values = _trade_returns_r(outcomes, sides, accepted, pt_atr, sl_atr, cost)
        item = _trade_metrics_r(values)
        item["round_trip_cost_atr"] = cost
        cost_sensitivity.append(item)

    return {
        "status": "complete",
        "model_type": "profit_aware_triple_barrier_meta_model",
        "selected_parameters": best["spec"],
        "selected_confidence_threshold": best["threshold"],
        "validation_positive_net_expectancy": best["positive_validation_edge"],
        "validation_trade_metrics": best["validation_trade_metrics"],
        "validation_threshold_search": best["threshold_table"],
        "validation_classification": best["validation_classification"],
        "untouched_test": test_metrics,
        "test_cost_sensitivity": cost_sensitivity,
        "round_trip_cost_atr_assumption": round_trip_cost_atr,
        "round_trip_cost_note": (
            "Cost is supplied as a fraction of ATR. Zero means no costs; "
            "use broker-observed spread plus commission and slippage converted to ATR."
        ),
        "split_samples": split_samples,
        "purge_overlapping_labels": True,
        "threshold_selected_on_validation_only": True,
        "model_selected_on_validation_net_expectancy": True,
        "test_used_for_selection": False,
        "embargo_bars": embargo_bars,
        "embargo_applied_at_split_boundaries": True,
        "accepted_barrier_outcomes": {
            "target_hits": sum(outcomes[i] == sides[i] for i in accepted),
            "stop_hits": sum(outcomes[i] == -sides[i] for i in accepted),
            "vertical_or_ambiguous": sum(outcomes[i] == 0 for i in accepted),
            "target_hit_rate_pct": round(
                sum(outcomes[i] == sides[i] for i in accepted) / len(accepted) * 100, 2
            ) if accepted else None,
        },
        "candidate_model_trained": True,
        "model_persisted": False,
        "production_model_persisted": False,
        "ai_trained": False,
        "research_only": True,
        "read_only": True,
        "execution_enabled": False,
        "accuracy_is_live": False,
        "limitations": [
            "The base trade side remains the completed-timeframe EMA10 trend rule.",
            "OHLC bars cannot resolve intrabar order when both barriers are touched; these events are conservatively neutral.",
            "Zero cost is not a profitability claim; supply broker-observed spread, commission and slippage in ATR units.",
            "Net R is a historical barrier outcome estimate, not a fill-level MT5 execution simulation.",
            "The untouched test is historical and not a newly collected forward period.",
            "Probability calibration is not performed.",
        ],
    }
