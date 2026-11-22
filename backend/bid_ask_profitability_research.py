"""Bid/ask-aware XAUUSD research evaluator.

Signals use completed bid candles. BUY fills use ask entry and bid exits;
SELL fills use bid entry and ask exits. Bid/ask OHLC extremes are not
tick-synchronized, so intrabar stop/target ordering remains conservative.
"""
from __future__ import annotations

import math

from profitability_research import _metrics, _signal, _validate


def _validate_pair(bid_candles, ask_candles):
    bid = _validate(bid_candles)
    ask = _validate(ask_candles)
    if len(bid) != len(ask):
        raise ValueError("Bid and ask candle counts must match.")
    if any(b["time"] != a["time"] for b, a in zip(bid, ask)):
        raise ValueError("Bid and ask candles must have identical timestamps.")
    for b, a in zip(bid, ask):
        if a["open"] < b["open"] or a["high"] < b["high"] or a["low"] < b["low"] or a["close"] < b["close"]:
            raise ValueError("Ask OHLC prices must not be below corresponding bid OHLC prices.")
    return bid, ask


def _simulate(bid, ask, start, end, horizon, stop_atr, target_r, commission_cost, slippage_cost):
    trades = []
    index = max(start, 56)
    while index < min(end, len(bid) - 1):
        setup = _signal(bid, index)
        if setup is None:
            index += 1
            continue
        side, atr = setup
        entry_index = index + 1
        # BUY crosses the spread upward; SELL enters on bid.
        entry = ask[entry_index]["open"] if side == 1 else bid[entry_index]["open"]
        risk = stop_atr * atr
        if risk <= 0:
            index += 1
            continue
        stop = entry - side * risk
        target = entry + side * risk * target_r
        exit_rows = bid if side == 1 else ask
        exit_price = exit_rows[min(end - 1, entry_index + horizon - 1)]["close"]
        exit_index = min(end - 1, entry_index + horizon - 1)
        reason = "time"
        for j in range(entry_index, min(end, entry_index + horizon)):
            candle = exit_rows[j]
            stop_gap = candle["open"] <= stop if side == 1 else candle["open"] >= stop
            target_gap = candle["open"] >= target if side == 1 else candle["open"] <= target
            if stop_gap:
                exit_price, exit_index, reason = candle["open"], j, "stop_gap"
                break
            if target_gap:
                exit_price, exit_index, reason = candle["open"], j, "target_gap"
                break
            stop_hit = candle["low"] <= stop if side == 1 else candle["high"] >= stop
            target_hit = candle["high"] >= target if side == 1 else candle["low"] <= target
            if stop_hit:
                exit_price, exit_index, reason = stop, j, "stop"
                break
            if target_hit:
                exit_price, exit_index, reason = target, j, "target"
                break
        gross = side * (exit_price - entry)
        costs = commission_cost + slippage_cost
        net_r = (gross - costs) / risk
        trades.append({
            "side": "BUY" if side == 1 else "SELL",
            "entry_time": bid[entry_index]["time"],
            "exit_time": exit_rows[exit_index]["time"],
            "entry": round(entry, 5),
            "exit": round(exit_price, 5),
            "exit_reason": reason,
            "net_r": round(net_r, 6),
        })
        index = max(index + 1, exit_index + 1)
    return trades


def evaluate_bid_ask_expectancy(
    bid_candles, ask_candles, horizon=24, stop_atr=1.5, target_r=2.0,
    commission_cost=0.0, slippage_cost=0.0, holdout_fraction=0.25,
):
    bid, ask = _validate_pair(bid_candles, ask_candles)
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 500:
        raise ValueError("horizon must be an integer from 1 to 500.")
    for name, value, minimum in (("stop_atr", stop_atr, 0.1), ("target_r", target_r, 0.1)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
            raise ValueError(f"{name} must be finite and at least {minimum}.")
    for name, value in (("commission_cost", commission_cost), ("slippage_cost", slippage_cost)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative.")
    if isinstance(holdout_fraction, bool) or not isinstance(holdout_fraction, (int, float)) or not 0.1 <= holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be between 0.1 and 0.5.")
    if len(bid) < 1000:
        return {"status": "insufficient_data", "candle_count": len(bid), "minimum_candles": 1000}
    boundary = int(len(bid) * (1.0 - holdout_fraction))
    dev = _simulate(bid, ask, 56, boundary - horizon, horizon, stop_atr, target_r, commission_cost, slippage_cost)
    test = _simulate(bid, ask, boundary - 1, len(bid), horizon, stop_atr, target_r, commission_cost, slippage_cost)
    dev_points = max(0, boundary - horizon - 56)
    test_points = max(0, len(bid) - boundary)
    spread = [a["open"] - b["open"] for b, a in zip(bid, ask)]
    return {
        "status": "complete",
        "execution_model": "BUY ask-entry/bid-exit; SELL bid-entry/ask-exit",
        "candle_count": len(bid),
        "time_split_index": boundary,
        "spread_at_open": {
            "mean": round(sum(spread) / len(spread), 5),
            "median": round(sorted(spread)[len(spread) // 2], 5),
            "p95": round(sorted(spread)[int((len(spread) - 1) * 0.95)], 5),
        },
        "parameters": {"horizon": horizon, "stop_atr": stop_atr, "target_r": target_r,
                       "commission_cost": commission_cost, "slippage_cost": slippage_cost},
        "development": _metrics(dev, dev_points, "development"),
        "holdout": _metrics(test, test_points, "untouched_chronological_holdout"),
        "directional_breakdown": {
            "development": {side.lower(): _metrics([t for t in dev if t["side"] == side], dev_points, side.lower()) for side in ("BUY", "SELL")},
            "holdout": {side.lower(): _metrics([t for t in test if t["side"] == side], test_points, side.lower()) for side in ("BUY", "SELL")},
        },
        "limitations": [
            "Dukascopy reference feed, not the user's broker execution feed.",
            "Bid/ask OHLC bars are not tick-synchronized; intrabar extremes may not have occurred in that order.",
            "Commission and slippage are additional price-unit deductions; swaps and latency are not modeled.",
            "Research-only; passing this test is not proof of future profitability.",
        ],
        "execution_enabled": False,
    }
