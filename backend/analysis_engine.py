"""Conservative multi-timeframe technical analysis for Gold AI.

This module calculates technical context only. It does not place trades and
must not be treated as an execution signal while the feed is not broker-specific.
"""
from __future__ import annotations

import math

from indicators.market_structure import analyse_market_structure


TIMEFRAME_WEIGHTS = {
    "H4": 3.0,
    "H1": 3.0,
    "M30": 2.0,
    "M15": 2.0,
    "M5": 1.0,
    "M1": 0.5,
}
REQUIRED_TIMEFRAMES = tuple(TIMEFRAME_WEIGHTS)
MIN_CANDLES = 60


def _ema_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    multiplier = 2.0 / (period + 1)
    current = seed
    for index in range(period, len(values)):
        current = (values[index] - current) * multiplier + current
        result[index] = current
    return result


def _rsi(values, period=14):
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(gains)):
        average_gain = ((average_gain * (period - 1)) + gains[index]) / period
        average_loss = ((average_loss * (period - 1)) + losses[index]) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _atr(candles, period=14):
    if len(candles) <= period:
        return None
    true_ranges = []
    previous_close = candles[0]["close"]
    for candle in candles[1:]:
        high = candle["high"]
        low = candle["low"]
        true_ranges.append(max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        ))
        previous_close = candle["close"]
    return sum(true_ranges[-period:]) / period


def _macd_histogram(values):
    if len(values) < 35:
        return None
    fast = _ema_series(values, 12)
    slow = _ema_series(values, 26)
    macd_values = [
        fast[index] - slow[index]
        for index in range(len(values))
        if fast[index] is not None and slow[index] is not None
    ]
    if len(macd_values) < 9:
        return None
    signal = _ema_series(macd_values, 9)
    return macd_values[-1] - signal[-1]


def _round_or_none(value, digits=4):
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _analyse_one_timeframe(timeframe, payload):
    candles = payload.get("candles") or []
    if len(candles) < MIN_CANDLES:
        return {
            "timeframe": timeframe,
            "status": "insufficient_data",
            "candle_count": len(candles),
            "score": 0,
            "bias": "NEUTRAL",
            "reason": f"Need at least {MIN_CANDLES} candles; received {len(candles)}.",
        }

    closes = [float(candle["close"]) for candle in candles]
    ema20_series = _ema_series(closes, 20)
    ema50_series = _ema_series(closes, 50)
    ema20 = ema20_series[-1]
    ema50 = ema50_series[-1]
    latest = closes[-1]
    rsi_value = _rsi(closes, 14)
    macd_hist = _macd_histogram(closes)
    atr_value = _atr(candles, 14)

    score = 0
    reasons = []

    if latest > ema20 > ema50:
        score += 2
        reasons.append("price is above rising EMA20/EMA50 structure")
    elif latest < ema20 < ema50:
        score -= 2
        reasons.append("price is below falling EMA20/EMA50 structure")
    elif ema20 > ema50:
        score += 1
        reasons.append("EMA20 is above EMA50")
    elif ema20 < ema50:
        score -= 1
        reasons.append("EMA20 is below EMA50")

    if rsi_value is not None:
        if 52 <= rsi_value <= 70:
            score += 1
            reasons.append("RSI momentum is bullish")
        elif 30 <= rsi_value <= 48:
            score -= 1
            reasons.append("RSI momentum is bearish")
        elif rsi_value > 70:
            reasons.append("RSI is elevated; bullish momentum is extended")
        elif rsi_value < 30:
            reasons.append("RSI is low; bearish momentum is extended")

    if macd_hist is not None:
        if macd_hist > 0:
            score += 1
            reasons.append("MACD histogram is positive")
        elif macd_hist < 0:
            score -= 1
            reasons.append("MACD histogram is negative")

    bias = "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"
    data_status = payload.get("data_status", "unknown")
    status = "ready" if data_status == "recent" else "stale_data"

    return {
        "timeframe": timeframe,
        "status": status,
        "data_status": data_status,
        "candle_count": len(candles),
        "last_candle_at": payload.get("last_candle_at"),
        "score": score,
        "bias": bias,
        "close": _round_or_none(latest, 2),
        "ema20": _round_or_none(ema20, 4),
        "ema50": _round_or_none(ema50, 4),
        "rsi14": _round_or_none(rsi_value, 2),
        "macd_histogram": _round_or_none(macd_hist, 5),
        "atr14": _round_or_none(atr_value, 4),
        "reason": "; ".join(reasons) if reasons else "Indicators are mixed.",
        "market_structure": analyse_market_structure(candles),
    }


def _market_regime(results, alignment_score):
    """Describe technical regime; this is not a probability or trade call."""
    required = ("H4", "H1", "M15", "M5")
    if any(tf not in results or results[tf].get("status") != "ready" for tf in required):
        return {"label":"UNCONFIRMED","direction":"NEUTRAL",
                "higher_timeframe_alignment":"UNCONFIRMED",
                "entry_timeframe_alignment":"UNCONFIRMED",
                "alignment_score":round(alignment_score,3),
                "explanation":"Recent H4, H1, M15 and M5 data are required.",
                "risk_note":"Stand aside until required data is complete and fresh."}
    h4,h1=results["H4"]["score"],results["H1"]["score"]
    m15,m5=results["M15"]["score"],results["M5"]["score"]
    higher="BULLISH" if h4>0 and h1>0 else "BEARISH" if h4<0 and h1<0 else "MIXED"
    entry="BULLISH" if m15>0 and m5>0 else "BEARISH" if m15<0 and m5<0 else "MIXED"
    if higher=="BULLISH" and alignment_score>=0.25:
        label,direction="UPTREND","BULLISH"
        explanation="Higher timeframes and the weighted score lean bullish."
        risk="Avoid chasing extended candles; wait for a tested pullback and broker-price confirmation."
    elif higher=="BEARISH" and alignment_score<=-0.25:
        label,direction="DOWNTREND","BEARISH"
        explanation="Higher timeframes and the weighted score lean bearish."
        risk="Avoid chasing extended candles; wait for a tested pullback and broker-price confirmation."
    elif abs(alignment_score)<=0.12 and higher!="MIXED":
        label,direction="POSSIBLE RANGE","NEUTRAL"
        explanation="Indicators are close to neutral; trend-following conditions are weak."
        risk="Breakouts can fail in range-like conditions; wait for a confirmed close beyond the range."
    else:
        label,direction="MIXED / TRANSITION","NEUTRAL"
        explanation="Timeframes disagree or trend strength is not decisive."
        risk="Conflicting conditions increase uncertainty. WAIT is the safer research stance."
    return {"label":label,"direction":direction,"higher_timeframe_alignment":higher,
            "entry_timeframe_alignment":entry,"alignment_score":round(alignment_score,3),
            "explanation":explanation,"risk_note":risk}


def analyse_timeframes(market_data):
    """Return a research-only directional bias from the six supplied timeframes."""
    results = {
        timeframe: _analyse_one_timeframe(timeframe, market_data[timeframe])
        for timeframe in REQUIRED_TIMEFRAMES
        if timeframe in market_data
    }
    missing = [timeframe for timeframe in REQUIRED_TIMEFRAMES if timeframe not in market_data]
    insufficient = [
        timeframe for timeframe, result in results.items()
        if result["status"] == "insufficient_data"
    ]
    stale = [
        timeframe for timeframe, result in results.items()
        if result["status"] == "stale_data"
    ]

    if missing or insufficient or stale:
        reasons = []
        if missing:
            reasons.append("Missing data: " + ", ".join(missing))
        if insufficient:
            reasons.append("Insufficient candle history: " + ", ".join(insufficient))
        if stale:
            reasons.append("Stale or unverified data: " + ", ".join(stale))
        return {
            "analysis_status": "data_not_ready",
            "research_signal": "WAIT",
            "technical_bias": "NEUTRAL",
            "alignment_score": 0,
            "market_regime": _market_regime(results, 0),
            "timeframes": results,
            "missing_timeframes": missing,
            "message": "No directional bias issued because all six timeframes must have sufficient, recent data. " + ". ".join(reasons) + ".",
        }

    weighted_score = sum(
        results[timeframe]["score"] * weight
        for timeframe, weight in TIMEFRAME_WEIGHTS.items()
    )
    maximum_score = sum(TIMEFRAME_WEIGHTS.values()) * 4.0
    alignment_score = weighted_score / maximum_score

    higher_bullish = results["H4"]["score"] > 0 and results["H1"]["score"] > 0
    higher_bearish = results["H4"]["score"] < 0 and results["H1"]["score"] < 0
    entry_bullish = results["M15"]["score"] > 0 and results["M5"]["score"] >= 0
    entry_bearish = results["M15"]["score"] < 0 and results["M5"]["score"] <= 0

    research_signal = "WAIT"
    if alignment_score >= 0.45 and higher_bullish and entry_bullish:
        research_signal = "BUY"
    elif alignment_score <= -0.45 and higher_bearish and entry_bearish:
        research_signal = "SELL"

    technical_bias = (
        "BULLISH" if alignment_score >= 0.20
        else "BEARISH" if alignment_score <= -0.20
        else "NEUTRAL"
    )

    if research_signal == "BUY":
        message = "The reference-feed indicators show a bullish multi-timeframe alignment. This is research-only, not a broker-confirmed trade signal."
    elif research_signal == "SELL":
        message = "The reference-feed indicators show a bearish multi-timeframe alignment. This is research-only, not a broker-confirmed trade signal."
    else:
        message = "The six timeframes do not meet the conservative alignment rules. No directional research signal is issued."

    return {
        "analysis_status": "complete",
        "research_signal": research_signal,
        "technical_bias": technical_bias,
        "alignment_score": round(alignment_score, 3),
        "market_regime": _market_regime(results, alignment_score),
        "timeframes": results,
        "missing_timeframes": [],
        "message": message,
    }
