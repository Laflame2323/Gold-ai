"""Pre-registered M30 sweep-and-reclaim research evaluator.

Research only. Signals use completed M30 bars; H1 context is aligned only
after the corresponding H1 bar has closed. The final 20% block is sealed
unless run_final_test=True is explicitly supplied after freeze approval.
"""
from __future__ import annotations

import math
import random


VERSION = "m30-sweep-reclaim-v1"
LOOKBACK = 20
ATR_PERIOD = 14
MAX_HOLD = 12
EMBARGO = 12


def _validate(rows, name):
    if not isinstance(rows, list):
        raise ValueError(f"{name} must be a list")
    result = []
    last_time = None
    for row in rows:
        try:
            stamp = int(row["time"])
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"{name} rows require numeric time and OHLC")
        if not all(math.isfinite(v) and v > 0 for v in values.values()):
            raise ValueError(f"{name} prices must be finite and positive")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"{name} has invalid high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"{name} has invalid low")
        if last_time is not None and stamp <= last_time:
            raise ValueError(f"{name} timestamps must be strictly increasing")
        last_time = stamp
        result.append({"time": stamp, **values})
    return result


def _atr(rows, end, period=ATR_PERIOD):
    if end < period:
        return None
    selected = rows[end - period + 1:end + 1]
    previous = rows[end - period]["close"]
    ranges = []
    for row in selected:
        ranges.append(max(row["high"] - row["low"],
                          abs(row["high"] - previous),
                          abs(row["low"] - previous)))
        previous = row["close"]
    value = sum(ranges) / period
    return value if value > 0 else None


def _ema(values, period):
    if len(values) < period:
        return None
    result = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for value in values[period:]:
        result += alpha * (value - result)
    return result


def _h1_context(m30_close_time, h1_rows):
    # H1 timestamps are bar-open times. Only bars whose close is no later
    # than the M30 decision timestamp are visible to the decision.
    completed = [row for row in h1_rows if row["time"] + 3600 <= m30_close_time]
    closes = [row["close"] for row in completed]
    fast = _ema(closes, 20)
    slow = _ema(closes, 50)
    slope = None
    if len(completed) >= 55:
        slope = _ema(closes, 20) - _ema(closes[:-5], 20)
    return {
        "completed_h1_bars": len(completed),
        "ema20": fast,
        "ema50": slow,
        "ema20_slope_5": slope,
        "ema_order": ("bullish" if fast is not None and slow is not None and fast > slow
                      else "bearish" if fast is not None and slow is not None and fast < slow
                      else "unavailable"),
    }


def _signal(rows, index):
    if index < max(LOOKBACK, ATR_PERIOD):
        return None
    bar = rows[index]
    prior = rows[index - LOOKBACK:index]
    prior_low = min(item["low"] for item in prior)
    prior_high = max(item["high"] for item in prior)
    span = bar["high"] - bar["low"]
    if span <= 0:
        return None
    body_ratio = abs(bar["close"] - bar["open"]) / span
    if body_ratio < 0.35:
        return None
    atr = _atr(rows, index)
    if atr is None:
        return None
    buy = (bar["low"] < prior_low and bar["close"] > prior_low
           and (bar["high"] - bar["close"]) / span <= 0.35)
    sell = (bar["high"] > prior_high and bar["close"] < prior_high
            and (bar["close"] - bar["low"]) / span <= 0.35)
    if buy == sell:  # neither or ambiguous both
        return None
    side = 1 if buy else -1
    sweep = bar["low"] if buy else bar["high"]
    entry_index = index + 1
    if entry_index >= len(rows):
        return None
    entry = rows[entry_index]["open"]
    stop = sweep - 0.10 * atr if buy else sweep + 0.10 * atr
    risk = entry - stop if buy else stop - entry
    if risk < 0.50 * atr or risk > 2.00 * atr:
        return None
    return {"side": side, "atr": atr, "sweep": sweep, "entry": entry,
            "risk": risk, "stop": stop, "target": entry + side * risk * 1.5}


def _session(timestamp):
    hour = (timestamp % 86400) // 3600
    if 0 <= hour < 7:
        return "Asia"
    if 7 <= hour < 13:
        return "London"
    if 13 <= hour < 21:
        return "NewYork"
    return "Rollover"


def _cost(session, session_costs):
    config = session_costs.get(session, {})
    values = [config.get(key, 0.0) for key in ("spread", "commission", "slippage")]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool)
           or not math.isfinite(value) or value < 0 for value in values):
        raise ValueError(f"Invalid non-negative cost configuration for {session}")
    return sum(values), dict(zip(("spread", "commission", "slippage"), values))


def _simulate(rows, h1_rows, start, end, session_costs):
    trades = []
    index = max(start, LOOKBACK, ATR_PERIOD)
    while index + 1 < end:
        setup = _signal(rows, index)
        if setup is None:
            index += 1
            continue
        side = setup["side"]
        entry_index = index + 1
        entry = rows[entry_index]["open"]
        stop, target, risk = setup["stop"], setup["target"], setup["risk"]
        last_exit = min(end - 1, entry_index + MAX_HOLD - 1)
        exit_price = rows[last_exit]["close"]
        exit_index, reason = last_exit, "time"
        for j in range(entry_index, last_exit + 1):
            bar = rows[j]
            stop_gap = bar["open"] <= stop if side == 1 else bar["open"] >= stop
            target_gap = bar["open"] >= target if side == 1 else bar["open"] <= target
            if stop_gap:
                exit_price, exit_index, reason = bar["open"], j, "stop_gap"
                break
            if target_gap:
                exit_price, exit_index, reason = bar["open"], j, "target_gap"
                break
            stop_hit = bar["low"] <= stop if side == 1 else bar["high"] >= stop
            target_hit = bar["high"] >= target if side == 1 else bar["low"] <= target
            if stop_hit:  # stop-first on ambiguous OHLC bars
                exit_price, exit_index, reason = stop, j, "stop"
                break
            if target_hit:
                exit_price, exit_index, reason = target, j, "target"
                break
        session = _session(rows[entry_index]["time"])
        cost, cost_parts = _cost(session, session_costs)
        gross = side * (exit_price - entry)
        net_r = (gross - cost) / risk
        decision_close_time = rows[index]["time"] + 1800
        trades.append({
            "side": "BUY" if side == 1 else "SELL",
            "signal_time": rows[index]["time"],
            "entry_time": rows[entry_index]["time"],
            "exit_time": rows[exit_index]["time"],
            "session": session,
            "entry": entry, "exit": exit_price, "stop": stop, "target": target,
            "risk": risk, "exit_reason": reason, "gross_r": gross / risk,
            "cost_price": cost, "cost_components": cost_parts, "net_r": net_r,
            "h1_context": _h1_context(decision_close_time, h1_rows),
        })
        index = exit_index + 1
    return trades


def _drawdown(values):
    equity = peak = max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _summary(trades, label, evaluated_bars, bootstrap_samples=1000, seed=17):
    values = [trade["net_r"] for trade in trades]
    n = len(values)
    wins = sum(value > 0 for value in values)
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    expectancy = sum(values) / n if n else None
    pf = gains / losses if losses else (None if not gains else "infinite")
    dd = _drawdown(values)
    rng = random.Random(seed)
    samples = {"win_rate": [], "expectancy": [], "profit_factor": [], "max_drawdown": []}
    if n:
        for _ in range(bootstrap_samples):
            draw = [values[rng.randrange(n)] for _ in range(n)]
            gp = sum(value for value in draw if value > 0)
            gl = -sum(value for value in draw if value < 0)
            samples["win_rate"].append(sum(value > 0 for value in draw) / n * 100)
            samples["expectancy"].append(sum(draw) / n)
            samples["profit_factor"].append(gp / gl if gl else (10_000.0 if gp else 0.0))
            samples["max_drawdown"].append(_drawdown(draw))
    def ci(key):
        values_ci = sorted(samples[key])
        if not values_ci:
            return None
        return [round(values_ci[int(0.025 * (len(values_ci) - 1))], 4),
                round(values_ci[int(0.975 * (len(values_ci) - 1))], 4)]
    return {
        "period": label, "trades": n,
        "trade_coverage_pct": round(n / evaluated_bars * 100, 3) if evaluated_bars else 0.0,
        "win_rate_pct": round(wins / n * 100, 3) if n else None,
        "expectancy_r": round(expectancy, 5) if n else None,
        "profit_factor": round(pf, 5) if isinstance(pf, float) else pf,
        "max_drawdown_r": round(dd, 5),
        "net_r": round(sum(values), 5),
        "bootstrap_95pct_ci": {
            "win_rate_pct": ci("win_rate"),
            "expectancy_r": ci("expectancy"),
            "profit_factor": ci("profit_factor"),
            "max_drawdown_r": ci("max_drawdown"),
            "method": "trade-level percentile bootstrap; not a guarantee; sequence dependence remains",
            "samples": bootstrap_samples if n else 0,
        },
    }


def evaluate_m30_sweep_reclaim(m30_candles, h1_candles, *,
                               session_costs=None, variant_count=1,
                               run_final_test=False):
    """Evaluate the frozen candidate on 60/20 blocks; final 20% stays sealed by default.

    Cost values are round-trip XAUUSD price units. Supply explicit costs per UTC
    session; omitted sessions default to zero and must be treated as uncalibrated.
    """
    m30 = _validate(m30_candles, "M30")
    h1 = _validate(h1_candles, "H1")
    if isinstance(variant_count, bool) or not isinstance(variant_count, int) or variant_count < 1:
        raise ValueError("variant_count must be a positive integer")
    costs = session_costs or {}
    if len(m30) < 1000 or len(h1) < 60:
        return {"status": "insufficient_data", "m30_count": len(m30), "h1_count": len(h1)}
    n = len(m30)
    first = int(n * 0.60)
    second = int(n * 0.80)
    # Exclude a 12-bar embargo on both sides of each boundary.
    dev_start, dev_end = LOOKBACK + ATR_PERIOD, max(LOOKBACK + ATR_PERIOD, first - EMBARGO)
    val_start, val_end = min(n, first + EMBARGO), max(min(n, first + EMBARGO), second - EMBARGO)
    final_start, final_end = min(n, second + EMBARGO), n
    development = _simulate(m30, h1, dev_start, dev_end, costs)
    validation = _simulate(m30, h1, val_start, val_end, costs)
    final = _simulate(m30, h1, final_start, final_end, costs) if run_final_test else None
    result = {
        "status": "complete",
        "candidate_version": VERSION,
        "preregistration": "M30 sweep-and-reclaim; body >=35%; close in outer 35%; next-open entry; stop beyond sweep by 0.10 ATR constrained to 0.50-2.00 ATR; 1.5R target; 12-bar maximum hold; stop-first OHLC ambiguity",
        "data": {"m30_candles": n, "h1_candles": len(h1), "m30_start": m30[0]["time"], "m30_end": m30[-1]["time"]},
        "split": {"development": [dev_start, dev_end], "validation": [val_start, val_end],
                  "final_test": [final_start, final_end], "embargo_bars": EMBARGO},
        "development": _summary(development, "development", dev_end - dev_start),
        "validation": _summary(validation, "validation", val_end - val_start),
        "final_test": (_summary(final, "final_test", final_end - final_start) if final is not None else "SEALED_NOT_RUN"),
        "cost_model": {"session_costs_price_units": costs, "sessions_utc": ["Asia", "London", "NewYork", "Rollover"]},
        "multiple_testing": {
            "strategy_variants_tested": variant_count,
            "warning": ("Multiple-testing risk is elevated; treat apparent edge as exploratory."
                        if variant_count > 1 else "One preregistered candidate declared; disclose any unlogged variants."),
        },
        "trade_details": {"development": development, "validation": validation,
                          "final_test": final if final is not None else []},
        "limitations": [
            "OHLC sweep/reclaim is a price-action proxy, not proof of institutional order flow.",
            "Zero or omitted session costs are not broker-calibrated and cannot support a profitability claim.",
            "Bootstrap intervals resample trades and do not remove serial dependence or regime risk.",
            "Final test is sealed unless explicitly opened after candidate and cost freeze.",
            "Research only; execution_enabled is false.",
        ],
        "execution_enabled": False,
    }
    return result
