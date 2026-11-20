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
from multitimeframe_features import build_multitimeframe_features
from causal_smc_features import FEATURE_NAMES as SMC_FEATURE_NAMES, causal_smc_features
from triple_barrier_research import BASE_INTERVALS, _atr, _metrics


def _weights(labels):
    counts = {label: labels.count(label) for label in set(labels)}
    if len(counts) < 2:
        raise ValueError("Training labels must contain at least two classes.")
    return [len(labels) / (len(counts) * counts[label]) for label in labels]


def _trade_returns_r(outcomes, sides, indices, pt_atr, sl_atr, cost_atr,
                     gross_returns_r=None):
    """Return per-setup net R, using realized timeout returns when supplied."""
    cost_r = cost_atr / sl_atr
    values = []
    for index in indices:
        if gross_returns_r is not None:
            gross_r = float(gross_returns_r[index])
        else:
            outcome, side = outcomes[index], sides[index]
            if outcome == side:
                gross_r = pt_atr / sl_atr
            elif outcome == -side:
                gross_r = -1.0
            else:
                gross_r = 0.0
        values.append(gross_r - cost_r)
    return values


def _simulate_directional_barrier(candles, index, horizon, pt_atr, sl_atr,
                                  atr_value, side):
    """Simulate one direction using executable bid/ask prices when available.

    Ambiguous same-bar target/stop touches assume stop-first. Vertical expiry is
    marked to the executable close rather than treated as a zero-return trade.
    """
    has_ask = all(
        all(key in candles[j] for key in ("ask_open", "ask_high", "ask_low", "ask_close"))
        for j in range(index + 1, index + horizon + 1)
    )
    entry_candle = candles[index + 1]
    if side > 0:
        entry = float(entry_candle.get("ask_open", entry_candle["open"]))
    else:
        entry = float(entry_candle["open"])
    target = entry + side * pt_atr * atr_value
    stop = entry - side * sl_atr * atr_value
    outcome = 0
    for j in range(index + 1, index + horizon + 1):
        candle = candles[j]
        if has_ask and side < 0:
            high, low = float(candle["ask_high"]), float(candle["ask_low"])
        else:
            high, low = float(candle["high"]), float(candle["low"])
        hit_target = (high >= target) if side > 0 else (low <= target)
        hit_stop = (low <= stop) if side > 0 else (high >= stop)
        if hit_target and hit_stop:
            return -side, j, -1.0, True
        if hit_target:
            return side, j, pt_atr / sl_atr, False
        if hit_stop:
            return -side, j, -1.0, False

    exit_candle = candles[index + horizon]
    if side > 0:
        exit_price = float(exit_candle["close"])
    else:
        exit_price = float(exit_candle.get("ask_close", exit_candle["close"]))
    gross_r = side * (exit_price - entry) / (atr_value * sl_atr)
    return outcome, index + horizon, gross_r, False


def _trade_metrics_r(values, max_range=None):
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
    value_range = max(values) - min(values) if max_range is None else max_range
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


def _select_threshold(probabilities, outcomes, sides, rows, pt_atr, sl_atr,
                       cost_atr, decisions=None, gross_returns_r=None):
    """Choose one side per validation candle; reject thin or weak candidates."""
    candidates = []
    decision_map = decisions if decisions is not None else list(range(len(outcomes)))
    unique_decisions = {decision_map[row] for row in rows}
    min_trades = max(20, int(math.ceil(len(unique_decisions) * 0.05)))
    best_by_decision = _best_side_rows(probabilities, rows, decision_map)
    for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90):
        selected = [row for probability, row in best_by_decision.values()
                    if probability >= threshold]
        values = _trade_returns_r(
            outcomes, sides, selected, pt_atr, sl_atr, cost_atr,
            gross_returns_r=gross_returns_r,
        )
        metrics = _trade_metrics_r(values, max_range=pt_atr / sl_atr + 1.0)
        metrics["coverage_pct"] = round(len(selected) / len(unique_decisions) * 100, 2)
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


def _regime_features(candles, index, atr_values):
    """Causal base-timeframe volatility, momentum and range-regime features."""
    current_atr = float(atr_values[index])
    current_close = float(candles[index]["close"])
    start = max(0, index - 49)
    recent_atr = [float(value) for value in atr_values[start:index + 1]
                  if value is not None and math.isfinite(value) and value > 0]
    atr_mean = sum(recent_atr) / len(recent_atr) if recent_atr else current_atr
    recent = candles[max(0, index - 19):index + 1]
    prior_high = max(float(item["high"]) for item in recent)
    prior_low = min(float(item["low"]) for item in recent)
    range_width = max(prior_high - prior_low, 1e-12)
    close_position = (current_close - prior_low) / range_width
    lookback_close = float(candles[max(0, index - 5)]["close"])
    momentum_5_atr = (current_close - lookback_close) / current_atr
    mean_bar_range = sum(
        float(item["high"]) - float(item["low"])
        for item in recent[-10:]
    ) / min(10, len(recent))
    current_range = float(candles[index]["high"]) - float(candles[index]["low"])
    return [
        current_atr / max(atr_mean, 1e-12),
        momentum_5_atr,
        range_width / current_atr,
        min(max(close_position, 0.0), 1.0),
        current_range / max(mean_bar_range, 1e-12),
    ]


def _calendar_features(timestamp):
    """Cyclical UTC hour and weekday features; uses decision time only."""
    day_number = int(timestamp) // 86400
    hour = (int(timestamp) % 86400) / 3600.0
    weekday = (day_number + 3) % 7  # 1970-01-01 was Thursday
    hour_angle = 2.0 * math.pi * hour / 24.0
    weekday_angle = 2.0 * math.pi * weekday / 7.0
    return [
        math.sin(hour_angle), math.cos(hour_angle),
        math.sin(weekday_angle), math.cos(weekday_angle),
    ]


def _make_directional_samples(candles_by_timeframe, horizon, pt_atr, sl_atr, base_timeframe):
    """Create BUY and SELL candidate labels for every completed base candle."""
    base = candles_by_timeframe.get(base_timeframe)
    if not isinstance(base, list) or len(base) < 1000:
        return None, {"status": "insufficient_data", "ai_trained": False,
                      "message": f"At least 1,000 {base_timeframe} candles are required."}
    bid_ask_prices_used = all(
        all(key in candle for key in ("ask_open", "ask_high", "ask_low", "ask_close"))
        for candle in base
    )
    feature_timeframes = (
        ("H4", "H1", "M30", "M15", "M5")
        if "M5" in candles_by_timeframe
        else ("H4", "H1", "M30", "M15")
    )
    aligned = build_multitimeframe_features(
        candles_by_timeframe, base_timeframe=base_timeframe,
        timeframes=feature_timeframes,
    )
    by_decision = {
        int(c["time"]) + BASE_INTERVALS[base_timeframe]: i
        for i, c in enumerate(base)
    }
    atr = _atr(base, 14)
    rows, outcomes, sides, gross_returns_r, decisions, label_ends = [], [], [], [], [], []
    counts = {"profit_target": 0, "stop_loss": 0, "vertical_or_no_touch": 0,
              "ambiguous_same_bar": 0, "missing_atr": 0}
    for item in aligned["rows"]:
        i = by_decision.get(item["decision_time"])
        if i is None or i + horizon >= len(base):
            continue
        if atr[i] is None or not math.isfinite(atr[i]) or atr[i] <= 0:
            counts["missing_atr"] += 1
            continue
        smc = causal_smc_features(base, i, atr[i])
        regime = _regime_features(base, i, atr)
        calendar = _calendar_features(item["decision_time"])
        spread_atr = (
            float(base[i].get("spread", 0.0) or 0.0) / float(atr[i])
        )
        for side in (-1, 1):
            outcome, end_index, gross_r, ambiguous = _simulate_directional_barrier(
                base, i, horizon, pt_atr, sl_atr, float(atr[i]), side
            )
            if ambiguous:
                counts["ambiguous_same_bar"] += 1
            elif outcome == side:
                counts["profit_target"] += 1
            elif outcome == -side:
                counts["stop_loss"] += 1
            else:
                counts["vertical_or_no_touch"] += 1
            rows.append(
                item["features"] + smc + regime + calendar + [spread_atr, float(side)]
            )
            outcomes.append(outcome)
            sides.append(side)
            gross_returns_r.append(gross_r)
            decisions.append(i)
            label_ends.append(end_index)
    if not rows:
        return None, {"status": "insufficient_data", "ai_trained": False,
                      "message": "No eligible directional barrier events were aligned."}
    return {
        "x": np.asarray(rows, dtype=np.float64), "outcomes": outcomes,
        "sides": sides, "gross_returns_r": gross_returns_r,
        "decisions": decisions, "label_ends": label_ends,
        "aligned": aligned, "counts": counts,
        "bid_ask_prices_used": bid_ask_prices_used,
    }, None


def _best_side_rows(probabilities, rows, decisions):
    """Keep only the highest-probability side for each candle decision."""
    best = {}
    for probability, row in zip(probabilities, rows):
        decision = decisions[row]
        current = best.get(decision)
        if current is None or probability > current[0]:
            best[decision] = (float(probability), row)
    return best


def evaluate_profit_aware_meta(candles_by_timeframe, horizon=24, pt_atr=1.5,
                               sl_atr=1.0, base_timeframe="M30",
                               round_trip_cost_atr=0.0,
                               include_test_diagnostic=False):
    """Train ephemeral candidates and select by validation net expectancy in R."""
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if not math.isfinite(round_trip_cost_atr) or not 0 <= round_trip_cost_atr <= 2:
        raise ValueError("round_trip_cost_atr must be between 0 and 2.")
    sample, error = _make_directional_samples(
        candles_by_timeframe, horizon, float(pt_atr), float(sl_atr), base_timeframe
    )
    if error:
        return error

    decisions = sample["decisions"]
    outcomes, sides, x = sample["outcomes"], sample["sides"], sample["x"]
    gross_returns_r = sample["gross_returns_r"]
    cost_r = round_trip_cost_atr / float(sl_atr)
    start, end = min(decisions), max(decisions) + 1
    span = end - start
    train_edge = start + int(span * 0.70)
    validation_edge = start + int(span * 0.85)

    # Keep BUY and SELL rows from the same candle in the same split.
    embargo_bars = horizon
    decision_label_end = {}
    for decision, label_end in zip(decisions, sample["label_ends"]):
        decision_label_end[decision] = max(
            decision_label_end.get(decision, 0), label_end
        )
    train = [i for i, decision in enumerate(decisions)
             if decision_label_end[decision] < train_edge
             and decision < train_edge - embargo_bars]
    validation = [i for i, decision in enumerate(decisions)
                  if decision >= train_edge + embargo_bars
                  and decision_label_end[decision] < validation_edge]
    test = [i for i, decision in enumerate(decisions)
            if decision >= validation_edge + embargo_bars]
    split_samples = {"train": len(train), "validation": len(validation), "test": len(test)}
    split_decisions = {
        name: len({decisions[i] for i in indices})
        for name, indices in (("train", train), ("validation", validation), ("test", test))
    }
    if min(split_samples.values()) < MIN_ROWS_PER_SPLIT:
        return {
            "status": "insufficient_data", "ai_trained": False,
            "eligible_samples": len(decisions), "eligible_decisions": len(set(decisions)),
            "split_samples": split_samples, "split_decisions": split_decisions,
            "minimum_samples_per_split": MIN_ROWS_PER_SPLIT,
        }

    labels = [
        int(gross_returns_r[i] - cost_r > 0)
        for i in range(len(gross_returns_r))
    ]
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
            round_trip_cost_atr, decisions=decisions,
            gross_returns_r=gross_returns_r,
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
        min_validation_trades = max(
            20, int(math.ceil(len({decisions[i] for i in validation}) * 0.05))
        )
        candidate_summaries = []
        provisional_candidates = []
        for candidate in evaluated:
            eligible_thresholds = [
                row for row in candidate["threshold_table"]
                if row["trades"] >= min_validation_trades
            ]
            top_lcb = max(
                eligible_thresholds,
                key=lambda row: row["mean_net_r_lower_90_bound"],
            ) if eligible_thresholds else None
            top_mean = max(
                eligible_thresholds,
                key=lambda row: row["mean_net_r"],
            ) if eligible_thresholds else None
            positive_mean_thresholds = []
            for row in eligible_thresholds:
                pf = row["profit_factor"]
                pf_above_one = pf == "infinite" or (
                    isinstance(pf, (int, float)) and pf > 1.0
                )
                if row["mean_net_r"] > 0 and pf_above_one:
                    positive_mean_thresholds.append(row)
            top_positive_mean = max(
                positive_mean_thresholds,
                key=lambda row: row["mean_net_r"],
            ) if positive_mean_thresholds else None
            top_validation_win_rate = max(
                eligible_thresholds,
                key=lambda row: (
                    row["net_positive_rate_pct"] if row["net_positive_rate_pct"] is not None else -1,
                    row["mean_net_r"],
                    row["trades"],
                ),
            ) if eligible_thresholds else None
            candidate_summaries.append({
                "model_parameters": candidate["spec"],
                "best_validation_threshold": top_lcb["threshold"] if top_lcb else None,
                "validation_trades": top_lcb["trades"] if top_lcb else 0,
                "validation_mean_net_r": top_lcb["mean_net_r"] if top_lcb else None,
                "validation_lower_90_bound_net_r": (
                    top_lcb["mean_net_r_lower_90_bound"] if top_lcb else None
                ),
                "validation_profit_factor": top_lcb["profit_factor"] if top_lcb else None,
                "validation_coverage_pct": top_lcb["coverage_pct"] if top_lcb else 0.0,
                "best_validation_mean_threshold": top_mean["threshold"] if top_mean else None,
                "best_validation_mean_net_r": top_mean["mean_net_r"] if top_mean else None,
                "best_validation_mean_lower_90_bound_net_r": (
                    top_mean["mean_net_r_lower_90_bound"] if top_mean else None
                ),
                "best_validation_mean_profit_factor": top_mean["profit_factor"] if top_mean else None,
                "best_validation_mean_trades": top_mean["trades"] if top_mean else 0,
                "best_validation_mean_coverage_pct": top_mean["coverage_pct"] if top_mean else 0.0,
                "best_positive_mean_threshold": (
                    top_positive_mean["threshold"] if top_positive_mean else None
                ),
                "best_positive_mean_net_r": (
                    top_positive_mean["mean_net_r"] if top_positive_mean else None
                ),
                "best_positive_mean_profit_factor": (
                    top_positive_mean["profit_factor"] if top_positive_mean else None
                ),
                "best_positive_mean_trades": (
                    top_positive_mean["trades"] if top_positive_mean else 0
                ),
                "best_positive_mean_lower_90_bound_net_r": (
                    top_positive_mean["mean_net_r_lower_90_bound"]
                    if top_positive_mean else None
                ),
                "best_positive_mean_coverage_pct": (
                    top_positive_mean["coverage_pct"] if top_positive_mean else 0.0
                ),
                "best_validation_win_rate_threshold": (
                    top_validation_win_rate["threshold"] if top_validation_win_rate else None
                ),
                "best_validation_win_rate_pct": (
                    top_validation_win_rate["net_positive_rate_pct"] if top_validation_win_rate else None
                ),
                "best_validation_win_rate_mean_net_r": (
                    top_validation_win_rate["mean_net_r"] if top_validation_win_rate else None
                ),
                "best_validation_win_rate_profit_factor": (
                    top_validation_win_rate["profit_factor"] if top_validation_win_rate else None
                ),
                "best_validation_win_rate_trades": (
                    top_validation_win_rate["trades"] if top_validation_win_rate else 0
                ),
                "best_validation_win_rate_coverage_pct": (
                    top_validation_win_rate["coverage_pct"] if top_validation_win_rate else 0.0
                ),
            })
            if top_validation_win_rate:
                provisional_candidates.append((candidate, top_validation_win_rate))

        provisional_test_diagnostic = None
        if include_test_diagnostic and provisional_candidates:
            provisional_candidate, provisional_row = max(
                provisional_candidates,
                key=lambda pair: (
                    pair[1]["net_positive_rate_pct"] if pair[1]["net_positive_rate_pct"] is not None else -1,
                    pair[1]["mean_net_r"],
                    pair[1]["trades"],
                ),
            )
            provisional_probabilities = provisional_candidate["model"].predict_proba(x[test])[
                :, list(provisional_candidate["model"].classes_).index(1)
            ]
            provisional_best_sides = _best_side_rows(
                provisional_probabilities, test, decisions
            )
            provisional_accepted = [
                row for probability, row in provisional_best_sides.values()
                if probability >= provisional_row["threshold"]
            ]
            provisional_returns = _trade_returns_r(
                outcomes, sides, provisional_accepted, pt_atr, sl_atr,
                round_trip_cost_atr, gross_returns_r=gross_returns_r,
            )
            provisional_test_metrics = _trade_metrics_r(
                provisional_returns, max_range=pt_atr / sl_atr + 1.0
            )
            test_decision_count = len({decisions[i] for i in test})
            provisional_test_metrics["coverage_pct"] = round(
                len(provisional_accepted) / test_decision_count * 100, 2
            )
            provisional_test_metrics["test_setups"] = test_decision_count
            provisional_test_metrics["directional_candidate_rows"] = len(test)
            provisional_test_metrics["classification"] = _metrics(
                test_y,
                provisional_candidate["model"].predict(x[test]).astype(int).tolist(),
            )
            provisional_cost_sensitivity = []
            for cost in (0.0, 0.025, 0.05, 0.10, 0.20):
                values = _trade_returns_r(
                    outcomes, sides, provisional_accepted, pt_atr, sl_atr, cost,
                    gross_returns_r=gross_returns_r,
                )
                metrics = _trade_metrics_r(
                    values, max_range=pt_atr / sl_atr + 1.0
                )
                metrics["round_trip_cost_atr"] = cost
                provisional_cost_sensitivity.append(metrics)
            provisional_test_diagnostic = {
                "model_parameters": provisional_candidate["spec"],
                "selected_confidence_threshold": provisional_row["threshold"],
                "validation_trade_metrics": provisional_row,
                "untouched_test": provisional_test_metrics,
                "test_cost_sensitivity": provisional_cost_sensitivity,
                "test_used_for_selection": False,
                "qualification": "diagnostic_only_selected_by_validation_win_rate_not_profitability",
            }

        return {
            "status": "no_positive_validation_edge",
            "message": "No candidate passed the conservative positive-expectancy lower-bound check.",
            "minimum_validation_trades": min_validation_trades,
            "candidate_validation_summary": candidate_summaries,
            "provisional_test_diagnostic": provisional_test_diagnostic,
            "split_samples": split_samples,
            "split_decisions": split_decisions,
            "candidate_models_evaluated": len(evaluated),
            "research_only": True,
            "read_only": True,
            "execution_enabled": False,
            "ai_trained": False,
            "model_persisted": False,
            "bid_ask_execution_prices_used": sample["bid_ask_prices_used"],
        }
    best = max(eligible_models, key=lambda item: (
        item["validation_trade_metrics"]["mean_net_r_lower_90_bound"],
        item["validation_trade_metrics"]["mean_net_r"],
        item["validation_trade_metrics"]["trades"],
    ))
    probabilities = best["model"].predict_proba(x[test])[:, list(best["model"].classes_).index(1)]
    best_test_sides = _best_side_rows(probabilities, test, decisions)
    accepted = [row for probability, row in best_test_sides.values()
                if probability >= best["threshold"]]
    test_returns = _trade_returns_r(
        outcomes, sides, accepted, pt_atr, sl_atr, round_trip_cost_atr,
        gross_returns_r=gross_returns_r,
    )
    test_metrics = _trade_metrics_r(test_returns, max_range=pt_atr / sl_atr + 1.0)
    test_decision_count = len({decisions[i] for i in test})
    test_metrics["coverage_pct"] = round(len(accepted) / test_decision_count * 100, 2)
    test_metrics["test_setups"] = test_decision_count
    test_metrics["directional_candidate_rows"] = len(test)
    test_metrics["classification"] = _metrics(
        test_y, best["model"].predict(x[test]).astype(int).tolist()
    )
    test_metrics["all_directional_candidates_net_positive_rate_pct"] = round(
        sum(test_y) / len(test_y) * 100, 2
    )
    test_metrics["all_directional_candidates_target_hit_rate_pct"] = round(
        sum(outcomes[i] == sides[i] for i in test) / len(test) * 100, 2
    )

    cost_sensitivity = []
    for cost in (0.0, 0.025, 0.05, 0.10, 0.20):
        values = _trade_returns_r(
            outcomes, sides, accepted, pt_atr, sl_atr, cost,
            gross_returns_r=gross_returns_r,
        )
        item = _trade_metrics_r(values, max_range=pt_atr / sl_atr + 1.0)
        item["round_trip_cost_atr"] = cost
        cost_sensitivity.append(item)

    return {
        "status": "complete",
        "model_type": "directional_profit_aware_triple_barrier_meta_model",
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
            "Cost is additional commission/slippage in ATR. When bid/ask OHLC is present, "
            "spread is already embedded in executable entries, exits and barrier touches. "
            "Without bid/ask OHLC, callers must include spread in this cost assumption."
        ),
        "bid_ask_execution_prices_used": sample["bid_ask_prices_used"],
        "split_samples": split_samples,
        "split_decisions": split_decisions,
        "eligible_samples": len(decisions),
        "eligible_decisions": len(set(decisions)),
        "directional_candidates_per_decision": 2,
        "calendar_features_timezone": "UTC",
        "purge_overlapping_labels": True,
        "threshold_selected_on_validation_only": True,
        "model_selected_on_validation_net_expectancy": True,
        "directional_side_selection_enabled": True,
        "one_trade_max_per_base_candle": True,
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
            "Both BUY and SELL candidates are scored per completed base-timeframe candle; the higher-probability side is selected.",
            "OHLC bars cannot resolve intrabar order when both barriers are touched; these events are conservatively neutral.",
            "Zero cost is not a profitability claim; supply broker-observed spread, commission and slippage in ATR units.",
            "Net R is a historical barrier outcome estimate, not a fill-level MT5 execution simulation.",
            "The untouched test is historical and not a newly collected forward period.",
            "Probability calibration is not performed.",
        ],
    }
