"""Cost-aware, risk-normalized XAUUSD strategy research.

Signals are decided after a completed candle and entered at the next candle open.
Intrabar ambiguity is resolved conservatively (stop before target). This module
is a research evaluator only: it never places orders and does not claim a live
win probability.
"""
from __future__ import annotations

import math


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for item in values[period:]:
        value += alpha * (item - value)
    return value


def _atr(candles, period=14):
    if len(candles) <= period:
        return None
    ranges = []
    previous = float(candles[-period - 1]["close"])
    for row in candles[-period:]:
        high, low = float(row["high"]), float(row["low"])
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
        previous = float(row["close"])
    return sum(ranges) / len(ranges)


def _validate(candles):
    if not isinstance(candles, list):
        raise ValueError("candles must be a list")
    rows = []
    previous_time = None
    for row in candles:
        try:
            timestamp = int(row["time"])
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Every candle needs numeric time, open, high, low and close.")
        if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)):
            raise ValueError("OHLC prices must be finite and positive.")
        if h < max(o, c, l) or l > min(o, c, h):
            raise ValueError("Invalid OHLC candle.")
        if previous_time is not None and timestamp <= previous_time:
            raise ValueError("Candles must be strictly time-ordered.")
        previous_time = timestamp
        rows.append({"time": timestamp, "open": o, "high": h, "low": l, "close": c})
    return rows


def _metrics(trades, evaluated_points, label):
    count = len(trades)
    wins = sum(t["net_r"] > 0 for t in trades)
    gross_profit = sum(max(0.0, t["net_r"]) for t in trades)
    gross_loss = abs(sum(min(0.0, t["net_r"]) for t in trades))
    equity = peak = max_dd = 0.0
    for trade in trades:
        equity += trade["net_r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "period": label,
        "trades": count,
        "win_rate_pct": round(wins / count * 100, 2) if count else None,
        "expectancy_r": round(sum(t["net_r"] for t in trades) / count, 4) if count else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if not gross_profit else "infinite"),
        "net_r": round(sum(t["net_r"] for t in trades), 4),
        "max_drawdown_r": round(max_dd, 4),
        "trade_coverage_pct": round(count / evaluated_points * 100, 3) if evaluated_points else 0.0,
    }


def _signal(rows, index, breakout_period=20):
    history = rows[:index + 1]
    closes = [r["close"] for r in history]
    if len(history) < max(55, breakout_period + 2):
        return None
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    atr = _atr(history, 14)
    if not atr or atr <= 0:
        return None
    prior = rows[index - breakout_period:index]
    prior_high = max(r["high"] for r in prior)
    prior_low = min(r["low"] for r in prior]
    last = rows[index]
    # BUY candidate: trend-confirmed range break.
    if closes[-1] > fast > slow and last["close"] > prior_high:
        return 1, atr

    # SELL candidate: require stronger bearish regime confirmation than BUY.
    # The slow EMA must be falling over five bars, the EMA gap must be
    # meaningful relative to ATR, and the breakout candle must close bearish.
    # This is a testable hypothesis, not an assertion that SELL is profitable.
    ema_history = [
        _ema([r["close"] for r in rows[:j + 1]], 50)
        for j in (index - 5, index)
    ]
    bearish_slope = (
        ema_history[0] is not None
        and ema_history[1] is not None
        and ema_history[1] < ema_history[0]
    )
    bearish_separation = fast < slow and (slow - fast) >= 0.15 * atr
    bearish_candle = last["close"] < last["open"]
    if (
        closes[-1] < fast < slow
        and last["close"] < prior_low
        and bearish_slope
        and bearish_separation
        and bearish_candle
    ):
        return -1, atr
    return None


def _simulate(rows, start, end, horizon, stop_atr, target_r, spread_cost, slippage_cost):
    trades = []
    index = max(start, 56)
    while index < min(end, len(rows) - 1):
        setup = _signal(rows, index)
        if setup is None:
            index += 1
            continue
        side, atr = setup
        entry_index = index + 1
        entry = rows[entry_index]["open"]
        risk = stop_atr * atr
        if risk <= 0:
            index += 1
            continue
        stop = entry - side * risk
        target = entry + side * risk * target_r
        costs = max(0.0, spread_cost) + max(0.0, slippage_cost)
        exit_price = rows[min(end - 1, entry_index + horizon - 1)]["close"]
        exit_index = min(end - 1, entry_index + horizon - 1)
        exit_reason = "time"
        for j in range(entry_index, min(end, entry_index + horizon)):
            candle = rows[j]
            # Model gaps at the next available open rather than granting a fill
            # at a stop/target price that the market has already crossed.
            stop_gap = candle["open"] <= stop if side == 1 else candle["open"] >= stop
            target_gap = candle["open"] >= target if side == 1 else candle["open"] <= target
            if stop_gap:
                exit_price, exit_index, exit_reason = candle["open"], j, "stop_gap"
                break
            if target_gap:
                exit_price, exit_index, exit_reason = candle["open"], j, "target_gap"
                break
            stop_hit = candle["low"] <= stop if side == 1 else candle["high"] >= stop
            target_hit = candle["high"] >= target if side == 1 else candle["low"] <= target
            if stop_hit:  # Conservative ordering when both are touched in one candle.
                exit_price, exit_index, exit_reason = stop, j, "stop"
                break
            if target_hit:
                exit_price, exit_index, exit_reason = target, j, "target"
                break
        gross = side * (exit_price - entry)
        net_r = (gross - costs) / risk
        trades.append({
            "side": "BUY" if side == 1 else "SELL",
            "entry_time": rows[entry_index]["time"],
            "exit_time": rows[exit_index]["time"],
            "entry": round(entry, 5),
            "exit": round(exit_price, 5),
            "exit_reason": exit_reason,
            "net_r": round(net_r, 6),
        })
        index = max(index + 1, exit_index + 1)
    return trades


def _directional_metrics(trades, evaluated_points):
    """Return separate BUY and SELL metrics using the same evaluation window."""
    output = {}
    for side in ("BUY", "SELL"):
        selected = [trade for trade in trades if trade["side"] == side]
        output[side.lower()] = _metrics(selected, evaluated_points, side.lower())
    return output


def evaluate_net_expectancy(
    candles, horizon=24, stop_atr=1.5, target_r=2.0,
    spread_cost=0.0, slippage_cost=0.0, holdout_fraction=0.25,
):
    """Evaluate one fixed breakout rule on chronological development/holdout blocks.

    spread_cost and slippage_cost are absolute XAUUSD price units per round trip.
    Costs must be calibrated to the user's broker; zero is a diagnostic only.
    """
    rows = _validate(candles)
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 500:
        raise ValueError("horizon must be an integer from 1 to 500.")
    for name, value, minimum in (("stop_atr", stop_atr, 0.1), ("target_r", target_r, 0.1)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
            raise ValueError(f"{name} must be finite and at least {minimum}.")
    for name, value in (("spread_cost", spread_cost), ("slippage_cost", slippage_cost)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative number.")
    if not isinstance(holdout_fraction, (int, float)) or isinstance(holdout_fraction, bool) or not 0.1 <= holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be between 0.1 and 0.5.")
    if len(rows) < 1000:
        return {"status": "insufficient_data", "candle_count": len(rows), "minimum_candles": 1000,
                "message": "At least 1,000 completed candles are required."}

    boundary = int(len(rows) * (1.0 - holdout_fraction))
    # Keep indicator warm-up but do not let development trades overlap holdout.
    development = _simulate(rows, 56, boundary - horizon, horizon, stop_atr, target_r, spread_cost, slippage_cost)
    holdout = _simulate(rows, boundary - 1, len(rows), horizon, stop_atr, target_r, spread_cost, slippage_cost)
    development_points = max(0, boundary - horizon - 56)
    holdout_points = max(0, len(rows) - boundary)
    dev_metrics = _metrics(development, development_points, "development")
    test_metrics = _metrics(holdout, holdout_points, "untouched_chronological_holdout")
    passed = (
        test_metrics["trades"] >= 30
        and isinstance(test_metrics["expectancy_r"], (int, float))
        and test_metrics["expectancy_r"] > 0
        and isinstance(test_metrics["profit_factor"], (int, float))
        and test_metrics["profit_factor"] > 1.0
    )
    return {
        "status": "complete",
        "strategy": "BUY: EMA20/EMA50 20-candle breakout; SELL: stricter bearish-slope, ATR-separation and bearish-candle breakout; ATR stop and fixed-R target",
        "candle_count": len(rows),
        "time_split_index": boundary,
        "parameters": {"horizon": horizon, "stop_atr": stop_atr, "target_r": target_r,
                       "spread_cost": spread_cost, "slippage_cost": slippage_cost},
        "development": dev_metrics,
        "holdout": test_metrics,
        "directional_breakdown": {
            "development": _directional_metrics(development, development_points),
            "holdout": _directional_metrics(holdout, holdout_points),
        },
        "research_gate": "candidate_passes_initial_gate" if passed else "not_proven_profitable",
        "minimum_holdout_trades_for_gate": 30,
        "limitations": [
            "Research-only; no broker orders are placed.",
            "The SELL entry filter is a new hypothesis and must be evaluated independently; it has not been proven superior.",
            "The same fixed parameters are used in both chronological blocks; no tuning on holdout.",
            "Stop is assumed before target when both are touched in one candle.",
            "Costs are simplified price deductions and must be calibrated to the broker.",
            "No swaps, commissions schedule, latency, partial fills or spread widening model.",
            "A passing result is only a candidate for demo-forward testing, not proof of future profit.",
        ],
        "execution_enabled": False,
        "ai_trained": False,
    }
