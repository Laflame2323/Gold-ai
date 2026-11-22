"""D1 XAUUSD high-hit-rate BUY hypothesis.

This is a research-only, fixed-rule evaluator. It deliberately does not place
orders and does not label a small or previously inspected sample as validated.
Signals use completed bid candles; entries use next-bar ask open; exits use bid.
"""
from __future__ import annotations

import math

from profitability_research import _metrics, _validate
from bid_ask_profitability_research import _validate_pair


def _ema_series(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        current += alpha * (values[i] - current)
        out[i] = current
    return out


def _wilder(values, period):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    current = sum(values[1:period + 1]) / period
    out[period] = current
    for i in range(period + 1, len(values)):
        current = (current * (period - 1) + values[i]) / period
        out[i] = current
    return out


def _indicators(rows, period=14):
    n = len(rows)
    closes = [r["close"] for r in rows]
    ema20, ema50, ema200 = (_ema_series(closes, p) for p in (20, 50, 200))
    tr, plus_dm, minus_dm = [0.0] * n, [0.0] * n, [0.0] * n
    gains, losses = [0.0] * n, [0.0] * n
    for i in range(1, n):
        prev = rows[i - 1]["close"]
        up = rows[i]["high"] - rows[i - 1]["high"]
        down = rows[i - 1]["low"] - rows[i]["low"]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(rows[i]["high"] - rows[i]["low"],
                    abs(rows[i]["high"] - prev), abs(rows[i]["low"] - prev))
        change = closes[i] - closes[i - 1]
        gains[i], losses[i] = max(change, 0.0), max(-change, 0.0)

    atr = _wilder(tr, period)
    avg_gain, avg_loss = _wilder(gains, period), _wilder(losses, period)
    rsi = [None] * n
    for i in range(n):
        if avg_gain[i] is not None and avg_loss[i] is not None:
            if avg_loss[i] == 0:
                rsi[i] = 100.0
            else:
                rs = avg_gain[i] / avg_loss[i]
                rsi[i] = 100.0 - 100.0 / (1.0 + rs)

    sm_plus, sm_minus = _wilder(plus_dm, period), _wilder(minus_dm, period)
    dx = [0.0] * n
    for i in range(n):
        if atr[i] and atr[i] > 0 and sm_plus[i] is not None:
            pdi = 100.0 * sm_plus[i] / atr[i]
            mdi = 100.0 * sm_minus[i] / atr[i]
            denom = pdi + mdi
            dx[i] = 100.0 * abs(pdi - mdi) / denom if denom else 0.0
    adx = _wilder(dx, period)
    return ema20, ema50, ema200, atr, rsi, adx


def _signals(rows, indicators, index, adx_min=15.0, rsi_min=50.0, rsi_max=80.0, breakout_period=40):
    ema20, ema50, ema200, atr, rsi, adx = indicators
    if index < max(200, breakout_period) or atr[index] is None or atr[index] <= 0:
        return False
    if any(series[index] is None for series in (ema20, ema50, ema200, rsi, adx)):
        return False
    previous_high = max(row["high"] for row in rows[index - breakout_period:index])
    last = rows[index]
    return (
        last["close"] > ema20[index] > ema50[index]
        and last["close"] > ema200[index]
        and last["close"] > previous_high
        and adx[index] >= adx_min
        and rsi_min <= rsi[index] <= rsi_max
    )


def _simulate(bid, ask, indicators, start, end, horizon, stop_atr,
              target_r, extra_cost, adx_min, rsi_min, rsi_max, breakout_period):
    trades = []
    index = max(start, 200)
    while index < min(end - 1, len(bid) - 1):
        if not _signals(bid, indicators, index, adx_min, rsi_min, rsi_max, breakout_period):
            index += 1
            continue
        entry_index = index + 1
        atr = indicators[3][index]
        entry = ask[entry_index]["open"]
        risk = stop_atr * atr
        stop, target = entry - risk, entry + risk * target_r
        last_index = min(end - 1, entry_index + horizon - 1)
        exit_price, exit_index, reason = bid[last_index]["close"], last_index, "time"
        for j in range(entry_index, min(end, entry_index + horizon)):
            candle = bid[j]
            if candle["open"] <= stop:
                exit_price, exit_index, reason = candle["open"], j, "stop_gap"
                break
            if candle["open"] >= target:
                exit_price, exit_index, reason = candle["open"], j, "target_gap"
                break
            # Conservative OHLC assumption: stop wins if both levels are touched.
            if candle["low"] <= stop:
                exit_price, exit_index, reason = stop, j, "stop"
                break
            if candle["high"] >= target:
                exit_price, exit_index, reason = target, j, "target"
                break
        net_r = ((exit_price - entry) - extra_cost) / risk
        trades.append({
            "side": "BUY", "entry_time": bid[entry_index]["time"],
            "exit_time": bid[exit_index]["time"], "entry": round(entry, 5),
            "exit": round(exit_price, 5), "exit_reason": reason,
            "net_r": round(net_r, 6),
        })
        index = max(index + 1, exit_index + 1)
    return trades


def evaluate_d1_buy_candidate(
    bid_candles, ask_candles, horizon=24, stop_atr=2.0, target_r=0.5,
    adx_min=15.0, rsi_min=50.0, rsi_max=80.0, breakout_period=40,
    commission_cost=0.0, slippage_cost=0.0, holdout_fraction=0.25,
):
    """Evaluate the fixed D1 BUY candidate on chronological development/holdout.

    Costs are additional absolute XAUUSD price units per round trip. The
    Dukascopy historical sample previously explored during research is not an
    untouched holdout; use genuinely new broker/demo data for validation.
    """
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

    indicators = _indicators(bid)
    boundary = int(len(bid) * (1.0 - holdout_fraction))
    if isinstance(breakout_period, bool) or not isinstance(breakout_period, int) or not 2 <= breakout_period <= 200:
        raise ValueError("breakout_period must be an integer from 2 to 200.")
    for name, value in (("adx_min", adx_min), ("rsi_min", rsi_min), ("rsi_max", rsi_max)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be finite and between 0 and 100.")
    if rsi_min > rsi_max:
        raise ValueError("rsi_min must not exceed rsi_max.")
    extra_cost = commission_cost + slippage_cost
    development = _simulate(bid, ask, indicators, 200, boundary - horizon,
                            horizon, stop_atr, target_r, extra_cost, adx_min, rsi_min, rsi_max, breakout_period)
    holdout = _simulate(bid, ask, indicators, boundary - 1, len(bid),
                        horizon, stop_atr, target_r, extra_cost, adx_min, rsi_min, rsi_max, breakout_period)
    dev_points = max(0, boundary - horizon - 200)
    test_points = max(0, len(bid) - boundary)
    holdout_metrics = _metrics(holdout, test_points, "chronological_holdout")
    passed = (
        holdout_metrics["trades"] >= 30
        and isinstance(holdout_metrics["expectancy_r"], (int, float))
        and holdout_metrics["expectancy_r"] > 0
        and isinstance(holdout_metrics["profit_factor"], (int, float))
        and holdout_metrics["profit_factor"] > 1.0
    )
    return {
        "status": "complete",
        "strategy": f"D1 BUY: close>EMA20>EMA50, close>EMA200, {breakout_period}-bar high breakout, ADX14>={adx_min}, RSI14 {rsi_min}-{rsi_max}",
        "execution_model": "next-bar ask entry; bid exits; stop-first OHLC handling",
        "parameters": {"horizon": horizon, "stop_atr": stop_atr, "target_r": target_r,
                       "adx_min": adx_min, "rsi_min": rsi_min, "rsi_max": rsi_max,
                       "breakout_period": breakout_period,
                       "commission_cost": commission_cost, "slippage_cost": slippage_cost},
        "candle_count": len(bid), "time_split_index": boundary,
        "development": _metrics(development, dev_points, "development"),
        "holdout": holdout_metrics,
        "research_gate": "candidate_passes_initial_gate" if passed else "not_proven_profitable",
        "minimum_holdout_trades_for_gate": 30,
        "limitations": [
            "This candidate was selected after inspecting the historical Dukascopy dataset; its historical holdout is not pristine.",
            "A 0.25R target against a 2R stop can produce a high win rate while retaining substantial loss risk.",
            "Dukascopy is a reference feed, not the user's broker execution feed.",
            "OHLC bars are not tick-synchronized; stop-first is a conservative assumption, not exact tick replay.",
            "No swap, latency, partial-fill or spread-widening model; costs require broker calibration.",
            "BUY D1 only; this result says nothing about SELL or intraday timeframes.",
            "Research only; execution is disabled.",
        ],
        "execution_enabled": False,
        "ai_trained": False,
    }
