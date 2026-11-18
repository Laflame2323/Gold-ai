"""Leakage-aware directional research backtest for completed gold candles.

Signals use only candles available at the decision close. Outcomes are measured
over a fixed number of later candles. This is a research diagnostic, not a
broker execution simulator; spreads, slippage, financing and intrabar paths
are not modelled.
"""
from __future__ import annotations

import math


def _ema(values, period):
    if len(values) < period:
        return None
    current = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for value in values[period:]:
        current += alpha * (value - current)
    return current


def _rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = ((period - 1) * avg_gain + gains[i]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema_series(values, period):
    output = [None] * len(values)
    if len(values) < period:
        return output
    current = sum(values[:period]) / period
    output[period - 1] = current
    alpha = 2.0 / (period + 1)
    for index in range(period, len(values)):
        current += alpha * (values[index] - current)
        output[index] = current
    return output


def _macd_histogram(values):
    if len(values) < 35:
        return None
    fast = _ema_series(values, 12)
    slow = _ema_series(values, 26)
    macd = [
        fast[index] - slow[index]
        for index in range(len(values))
        if fast[index] is not None and slow[index] is not None
    ]
    signal_series = _ema_series(macd, 9)
    if not signal_series or signal_series[-1] is None:
        return None
    return macd[-1] - signal_series[-1]


def _signal_for_prefix(closes):
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi = _rsi(closes)
    macd_hist = _macd_histogram(closes)
    if None in (ema20, ema50, rsi, macd_hist):
        return "WAIT"
    latest = closes[-1]
    if latest > ema20 > ema50 and rsi >= 52 and macd_hist > 0:
        return "BUY"
    if latest < ema20 < ema50 and rsi <= 48 and macd_hist < 0:
        return "SELL"
    return "WAIT"


def run_directional_backtest(candles, horizon=5, minimum_samples=100):
    """Backtest a conservative EMA/RSI/MACD rule on ordered completed candles."""
    if not isinstance(candles, list):
        raise ValueError("candles must be a list")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 1 and 100")
    if isinstance(minimum_samples, bool) or not isinstance(minimum_samples, int) or minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")
    # Decision indices start at 59 and end at len(candles) - horizon - 1.
    # Require the requested number of genuinely scoreable decision points.
    required_candles = 59 + minimum_samples + horizon
    if len(candles) < required_candles:
        return {
            "status": "insufficient_data",
            "candle_count": len(candles),
            "horizon_candles": horizon,
            "minimum_evaluated_decision_points": minimum_samples,
            "required_candle_count": required_candles,
            "message": "More completed historical candles are required before testing.",
        }

    normalized = []
    previous_time = None
    for candle in candles:
        try:
            timestamp = int(candle["time"])
            open_price = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Each candle must contain valid time, open, high, low and close.")
        values = (open_price, high, low, close)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("Candle prices must be finite positive numbers.")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Candle OHLC values are inconsistent.")
        if previous_time is not None and timestamp <= previous_time:
            raise ValueError("Candles must be strictly ordered by increasing time.")
        previous_time = timestamp
        normalized.append({"time": timestamp, "close": close})

    trades = []
    # The last horizon candles cannot be scored because their future outcome
    # is not yet present. The prefix ends at the decision candle.
    for index in range(59, len(normalized) - horizon):
        prefix_closes = [row["close"] for row in normalized[:index + 1]]
        signal = _signal_for_prefix(prefix_closes)
        if signal == "WAIT":
            continue
        entry = normalized[index]["close"]
        exit_price = normalized[index + horizon]["close"]
        signed_return_pct = ((exit_price / entry) - 1.0) * 100.0
        if signal == "SELL":
            signed_return_pct *= -1.0
        trades.append({
            "signal": signal,
            "entry_time": normalized[index]["time"],
            "exit_time": normalized[index + horizon]["time"],
            "signed_return_pct": signed_return_pct,
            "correct": signed_return_pct > 0,
        })

    total = len(trades)
    buys = [trade for trade in trades if trade["signal"] == "BUY"]
    sells = [trade for trade in trades if trade["signal"] == "SELL"]
    wins = sum(1 for trade in trades if trade["correct"])
    accuracy = (wins / total * 100.0) if total else None
    avg_return = (sum(t["signed_return_pct"] for t in trades) / total) if total else None

    def side_stats(side_trades):
        count = len(side_trades)
        wins_side = sum(1 for trade in side_trades if trade["correct"])
        return {
            "signals": count,
            "win_rate_pct": round(wins_side / count * 100.0, 2) if count else None,
            "average_signed_return_pct": round(
                sum(t["signed_return_pct"] for t in side_trades) / count, 4
            ) if count else None,
        }

    evaluated = max(0, len(normalized) - horizon - 59)
    coverage = (total / evaluated * 100.0) if evaluated else 0.0
    return {
        "status": "complete",
        "strategy": "EMA20/EMA50 trend + RSI14 + MACD histogram confirmation",
        "candle_count": len(normalized),
        "evaluated_decision_points": evaluated,
        "horizon_candles": horizon,
        "signals_tested": total,
        "coverage_pct": round(coverage, 2),
        "accuracy_pct": round(accuracy, 2) if accuracy is not None else None,
        "average_signed_return_pct": round(avg_return, 4) if avg_return is not None else None,
        "buy": side_stats(buys),
        "sell": side_stats(sells),
        "limitations": [
            "Research-only directional test; no orders are placed.",
            "Uses close-to-close outcomes over a fixed candle horizon.",
            "Spread, commission, slippage, swaps and execution delays are excluded.",
            "Overlapping signal outcomes are allowed and are not independent samples.",
            "Historical results do not guarantee future performance.",
        ],
        "message": (
            "No qualifying BUY or SELL signals occurred in the tested window."
            if not total else
            "Results are historical diagnostics, not a live accuracy guarantee."
        ),
    }
