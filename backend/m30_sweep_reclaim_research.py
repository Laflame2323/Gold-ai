"""Frozen deterministic M30 sweep-and-reclaim evaluator. Research only."""
from __future__ import annotations
import hashlib, json, math, random
from dataclasses import asdict, dataclass
from typing import Any, Literal

VERSION = "m30-sweep-reclaim-v1"
LOOKBACK, ATR_PERIOD, MAX_HOLDING_BARS, EMBARGO_BARS = 20, 14, 12, 12
M30_SECONDS, H1_SECONDS = 1800, 3600
SUPPORTED_EVAL_MODES = {"development", "validation", "development_validation", "final_test"}

@dataclass(frozen=True)
class TradePlan:
    candidate_version: str
    dataset_fingerprint: str
    side: Literal["BUY", "SELL"]
    signal_time: int
    entry_time: int
    entry_price: float
    stop_price: float
    target_price: float
    risk_price: float
    reward_price: float
    max_holding_bars: int
    atr: float
    sweep_extreme: float
    prior_range_high: float
    prior_range_low: float
    body_ratio: float
    close_position: float
    h1_context: tuple[tuple[str, Any], ...]
    assumptions: tuple[tuple[str, Any], ...]

def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, not bool")
    try: result = float(value)
    except (TypeError, ValueError, OverflowError): raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be finite" + (" and > 0" if positive else ""))
    return result

def _timestamp(value: Any, name: str) -> int:
    if isinstance(value, bool): raise ValueError(f"{name} must be an integer Unix timestamp")
    try: result = int(value)
    except (TypeError, ValueError, OverflowError): raise ValueError(f"{name} must be an integer Unix timestamp") from None
    if str(value).strip() not in (str(result), f"{result}.0") or result <= 0:
        raise ValueError(f"{name} must be an exact positive integer Unix timestamp")
    return result

def _validate_candles(rows: list[dict], label: str) -> list[dict]:
    if not isinstance(rows, list) or not rows: raise ValueError(f"{label} must be a non-empty list")
    cleaned, previous = [], None
    for index, row in enumerate(rows):
        if not isinstance(row, dict): raise ValueError(f"{label}[{index}] must be a dict")
        stamp = _timestamp(row.get("time", row.get("timestamp")), f"{label}[{index}].time")
        values = {key: _number(row.get(key), f"{label}[{index}].{key}", positive=True)
                  for key in ("open", "high", "low", "close")}
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"{label}[{index}] has inconsistent OHLC high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"{label}[{index}] has inconsistent OHLC low")
        if previous is not None and stamp <= previous: raise ValueError(f"{label} timestamps must be strictly increasing")
        previous = stamp
        cleaned.append({"time": stamp, **values})
    return cleaned

def _fingerprint(m30: list[dict], h1: list[dict]) -> str:
    raw = json.dumps({"m30": m30, "h1": h1}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

def _wilder_atr(rows: list[dict], period: int = ATR_PERIOD) -> list[float | None]:
    values: list[float | None] = [None] * len(rows)
    if len(rows) <= period: return values
    trs = []
    for i in range(1, len(rows)):
        row, prev = rows[i], rows[i - 1]["close"]
        trs.append(max(row["high"] - row["low"], abs(row["high"] - prev), abs(row["low"] - prev)))
    current = sum(trs[:period]) / period
    values[period] = current
    for k in range(period, len(trs)):
        current = (current * (period - 1) + trs[k]) / period
        values[k + 1] = current
    return values

def _ema_series(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period: return out
    alpha, current = 2.0 / (period + 1), sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out

def _h1_context(decision_close_time: int, h1: list[dict]) -> dict[str, Any] | None:
    completed = [r for r in h1 if r["time"] + H1_SECONDS <= decision_close_time]
    if len(completed) < 50: return None
    closes = [r["close"] for r in completed]
    e20, e50 = _ema_series(closes, 20), _ema_series(closes, 50)
    slope = e20[-1] - e20[-2]
    return {
        "last_completed_h1_open": completed[-1]["time"], "completed_h1_bars": len(completed),
        "ema20": e20[-1], "ema50": e50[-1], "ema20_slope_1_h1_bar": slope,
        "ema_order": "bullish" if e20[-1] > e50[-1] else "bearish" if e20[-1] < e50[-1] else "flat",
        "slope_definition": "current completed-H1 EMA20 minus previous completed-H1 EMA20",
    }

def _detect_signal(rows: list[dict], atrs: list[float | None], index: int) -> dict | None:
    if index < max(LOOKBACK, ATR_PERIOD) or atrs[index] is None or atrs[index] <= 0: return None
    c, atr = rows[index], atrs[index]
    prior = rows[index - LOOKBACK:index]
    ph, pl = max(r["high"] for r in prior), min(r["low"] for r in prior)
    span = c["high"] - c["low"]
    if span <= 0: return None
    body_ratio, close_pos = abs(c["close"] - c["open"]) / span, (c["close"] - c["low"]) / span
    buy = c["low"] < pl and c["close"] > pl
    sell = c["high"] > ph and c["close"] < ph
    if buy and sell: return {"rejected": "ambiguous_buy_and_sell"}
    if not buy and not sell: return None
    side = "BUY" if buy else "SELL"
    if body_ratio < 0.35: return {"rejected": "body_below_35_percent", "side": side}
    if side == "BUY" and close_pos < 0.65: return {"rejected": "buy_close_not_in_upper_35_percent", "side": side}
    if side == "SELL" and close_pos > 0.35: return {"rejected": "sell_close_not_in_lower_35_percent", "side": side}
    return {"side": side, "atr": atr, "sweep_extreme": c["low"] if buy else c["high"],
            "prior_range_high": ph, "prior_range_low": pl, "body_ratio": body_ratio, "close_position": close_pos}

def _simulate_segment(m30, h1, atrs, start, end, fingerprint, candidate_version, cost):
    plans, outcomes, rejected, last_exit_index = [], [], [], -1
    for i in range(max(start, LOOKBACK, ATR_PERIOD), end - 1):
        sig = _detect_signal(m30, atrs, i)
        if sig is None: continue
        ts = m30[i]["time"]
        if "rejected" in sig:
            rejected.append({"signal_time": ts, **sig}); continue
        if i <= last_exit_index:
            rejected.append({"signal_time": ts, "side": sig["side"], "reason": "overlapping_position"}); continue
        entry_i, entry_bar = i + 1, m30[i + 1]
        entry, atr, side, sweep = entry_bar["open"], sig["atr"], sig["side"], sig["sweep_extreme"]
        stop = sweep - .10 * atr if side == "BUY" else sweep + .10 * atr
        risk = entry - stop if side == "BUY" else stop - entry
        risk_atr = risk / atr
        if risk <= 0 or risk_atr < .50 or risk_atr > 2.00:
            rejected.append({"signal_time": ts, "side": side,
                             "reason": "entry_open_stop_distance_outside_0.50_to_2.00_ATR", "risk_atr": risk_atr})
            continue
        ctx = _h1_context(ts + M30_SECONDS, h1)
        if ctx is None:
            rejected.append({"signal_time": ts, "side": side, "reason": "insufficient_completed_h1_context"}); continue
        target = entry + 1.5 * risk if side == "BUY" else entry - 1.5 * risk
        plan = TradePlan(
            candidate_version, fingerprint, side, ts, entry_bar["time"], entry, stop, target,
            risk, 1.5 * risk, MAX_HOLDING_BARS, atr, sweep, sig["prior_range_high"], sig["prior_range_low"],
            sig["body_ratio"], sig["close_position"], tuple(ctx.items()),
            tuple({"entry": "next available M30 open", "atr": "Wilder ATR(14), through completed signal candle",
             "stop_buffer_atr": .10, "stop_distance_atr_min": .50, "stop_distance_atr_max": 2.00,
             "target_r": 1.5, "max_holding_bars_including_entry_bar": 12,
             "same_bar_stop_target": "stop first", "opening_gap": "fill at open if crossed",
             "h1_slope": "EMA20 now minus previous completed-H1 EMA20"}.items()))
        pd = asdict(plan)
        pd["h1_context"] = dict(plan.h1_context)
        pd["assumptions"] = dict(plan.assumptions)
        plans.append(pd)
        last_allowed = min(entry_i + MAX_HOLDING_BARS - 1, end - 1)
        exit_price = exit_i = None
        reason = None
        for j in range(entry_i, last_allowed + 1):
            b = m30[j]
            if side == "BUY":
                if b["open"] <= stop: exit_price, exit_i, reason = b["open"], j, "stop_gap"; break
                if b["open"] >= target: exit_price, exit_i, reason = b["open"], j, "target_gap"; break
                if b["low"] <= stop: exit_price, exit_i, reason = stop, j, "stop"; break
                if b["high"] >= target: exit_price, exit_i, reason = target, j, "target"; break
            else:
                if b["open"] >= stop: exit_price, exit_i, reason = b["open"], j, "stop_gap"; break
                if b["open"] <= target: exit_price, exit_i, reason = b["open"], j, "target_gap"; break
                if b["high"] >= stop: exit_price, exit_i, reason = stop, j, "stop"; break
                if b["low"] <= target: exit_price, exit_i, reason = target, j, "target"; break
        if exit_price is None:
            if last_allowed - entry_i + 1 < MAX_HOLDING_BARS:
                rejected.append({"signal_time": ts, "side": side, "reason": "trade_censored_at_segment_boundary"})
                plans.pop(); continue
            exit_i, exit_price, reason = last_allowed, m30[last_allowed]["close"], "time"
        gross = (exit_price - entry) / risk if side == "BUY" else (entry - exit_price) / risk
        cost_r = cost / risk if cost is not None else None
        outcomes.append({"plan": pd, "exit_time": m30[exit_i]["time"], "exit_price": exit_price,
                         "exit_reason": reason, "exit_index": exit_i, "bars_held": exit_i - entry_i + 1,
                         "gross_r": gross, "cost_r": cost_r, "net_r": gross - cost_r if cost_r is not None else None})
        last_exit_index = exit_i
    return {"plans": plans, "outcomes": outcomes, "rejected": rejected}

def _block_bootstrap_expectancy_ci(rows, value_key="gross_r", *, block_length=5, replications=2000, seed=20261125):
    """Deterministic circular moving-block bootstrap over chronological trade outcomes."""
    if value_key not in {"gross_r", "net_r"}:
        raise ValueError("value_key must be gross_r or net_r")
    if isinstance(block_length, bool) or not isinstance(block_length, int) or block_length < 1:
        raise ValueError("block_length must be a positive integer")
    if isinstance(replications, bool) or not isinstance(replications, int) or replications < 100:
        raise ValueError("replications must be an integer >= 100")
    ordered_rows = sorted(rows, key=lambda row: (row.get("exit_index", 0), row.get("exit_time", 0)))
    values = [float(row[value_key]) for row in ordered_rows if row.get(value_key) is not None]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("bootstrap values must be finite")
    n = len(values)
    if n < 2 * block_length:
        return {"status": "insufficient_independent_blocks", "n": n, "block_length_trades": block_length,
                "replications": 0, "expectancy_r": None, "ci_95_lower": None, "ci_95_upper": None}
    rng = random.Random(seed)
    estimates = []
    for _ in range(replications):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + offset) % n] for offset in range(block_length))
        sample = sample[:n]
        estimates.append(sum(sample) / n)
    estimates.sort()
    def percentile(p):
        position = (len(estimates) - 1) * p
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return estimates[lower]
        return estimates[lower] + (estimates[upper] - estimates[lower]) * (position - lower)
    return {"status": "complete", "n": n, "block_length_trades": block_length,
            "replications": replications, "seed": seed,
            "expectancy_r": sum(values) / n,
            "ci_95_lower": percentile(0.025), "ci_95_upper": percentile(0.975),
            "method": "circular_moving_block_bootstrap_over_chronological_trades"}


def _stats(rows, net=False):
    vals = [r["net_r" if net else "gross_r"] for r in rows if r["net_r" if net else "gross_r"] is not None]
    if not vals:
        return {"trades": 0, "win_rate_pct": None, "expectancy_r": None, "median_r": None,
                "profit_factor": None, "max_drawdown_r": 0.0}
    wins, losses = [v for v in vals if v > 0], [v for v in vals if v < 0]
    gp, gl = sum(wins), abs(sum(losses))
    eq = peak = dd = 0.0
    for v in vals:
        eq += v; peak = max(peak, eq); dd = max(dd, peak - eq)
    ordered, mid = sorted(vals), len(vals) // 2
    median = ordered[mid] if len(vals) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    longest_losing_streak = current_losing_streak = 0
    for value in vals:
        if value < 0:
            current_losing_streak += 1
            longest_losing_streak = max(longest_losing_streak, current_losing_streak)
        else:
            current_losing_streak = 0
    holding = [int(row["bars_held"]) for row in rows if row.get("bars_held") is not None]
    holding_sorted = sorted(holding)
    if holding_sorted:
        hmid = len(holding_sorted) // 2
        holding_median = holding_sorted[hmid] if len(holding_sorted) % 2 else (holding_sorted[hmid - 1] + holding_sorted[hmid]) / 2
    else:
        holding_median = None
    return {"trades": len(vals), "win_rate_pct": 100 * len(wins) / len(vals),
            "expectancy_r": sum(vals) / len(vals), "median_r": median,
            "profit_factor": gp / gl if gl else ("infinite" if gp else None), "max_drawdown_r": dd,
            "longest_losing_streak": longest_losing_streak,
            "holding_bars_mean": sum(holding) / len(holding) if holding else None,
            "holding_bars_median": holding_median}

def evaluate_m30_sweep_reclaim(
    m30_candles: list[dict], h1_candles: list[dict] | None = None, *,
    dataset_fingerprint: str | None = None, candidate_version: str = VERSION,
    round_trip_cost_price_units: float | None = None, cost_scenarios: dict[str, float] | None = None,
    evaluation_mode: str = "development_validation", allow_final_test: bool = False,
    candidate_frozen: bool = False, costs_frozen: bool = False,
) -> dict:
    """Evaluate fixed rules. Final test requires three explicit freeze/authorization gates."""
    if evaluation_mode not in SUPPORTED_EVAL_MODES: raise ValueError(f"evaluation_mode must be one of {sorted(SUPPORTED_EVAL_MODES)}")
    if evaluation_mode == "final_test" and not (allow_final_test and candidate_frozen and costs_frozen):
        raise PermissionError("final_test requires allow_final_test, candidate_frozen and costs_frozen")
    if not isinstance(candidate_version, str) or not candidate_version.strip(): raise ValueError("candidate_version is required")
    if round_trip_cost_price_units is not None:
        round_trip_cost_price_units = _number(round_trip_cost_price_units, "round_trip_cost_price_units")
        if round_trip_cost_price_units < 0: raise ValueError("round_trip_cost_price_units must be >= 0")
    scenarios = {}
    for label, value in (cost_scenarios or {}).items():
        if not isinstance(label, str) or not label: raise ValueError("cost scenario names must be non-empty")
        val = _number(value, f"cost_scenarios[{label}]")
        if val < 0: raise ValueError("cost scenarios must be >= 0")
        scenarios[label] = val
    m30 = _validate_candles(m30_candles, "m30_candles")
    if h1_candles is None: raise ValueError("H1 candles are required by preregistration; missing context fails closed")
    h1 = _validate_candles(h1_candles, "h1_candles")
    candle_payload_sha256 = _fingerprint(m30, h1)
    fingerprint = dataset_fingerprint or candle_payload_sha256
    if not isinstance(fingerprint, str) or not fingerprint.strip(): raise ValueError("dataset_fingerprint must be non-empty")
    if len(m30) < 100 or len(h1) < 55:
        return {"status": "insufficient_data", "m30_count": len(m30), "h1_count": len(h1),
                "dataset_fingerprint": fingerprint, "candle_payload_sha256": candle_payload_sha256,
                "execution_enabled": False}
    atrs, n = _wilder_atr(m30), len(m30)
    first, second = int(n * .60), int(n * .80)
    splits = {"development": (0, max(0, first - EMBARGO_BARS)),
              "validation": (min(n, first + EMBARGO_BARS), max(min(n, first + EMBARGO_BARS), second - EMBARGO_BARS)),
              "final_test": (min(n, second + EMBARGO_BARS), n)}
    selected = ["development", "validation"] if evaluation_mode == "development_validation" else [evaluation_mode]
    periods = {}
    for name in selected:
        start, end = splits[name]
        result = _simulate_segment(m30, h1, atrs, start, end, fingerprint, candidate_version, round_trip_cost_price_units)
        trades = result["outcomes"]
        sides = {s: [r for r in trades if r["plan"]["side"] == s] for s in ("BUY", "SELL")}
        period = {"signal_plans": len(result["plans"]), "rejected": result["rejected"],
                  "BUY": {"gross": _stats(sides["BUY"]), "net": _stats(sides["BUY"], True)},
                  "SELL": {"gross": _stats(sides["SELL"]), "net": _stats(sides["SELL"], True)},
                  "combined": {"gross": _stats(trades), "net": _stats(trades, True)},
                  "uncertainty": {
                      "method": "circular moving-block bootstrap over chronological trades",
                      "BUY_gross_expectancy_95_ci": _block_bootstrap_expectancy_ci(sides["BUY"], "gross_r"),
                      "BUY_net_expectancy_95_ci": _block_bootstrap_expectancy_ci(sides["BUY"], "net_r"),
                      "SELL_gross_expectancy_95_ci": _block_bootstrap_expectancy_ci(sides["SELL"], "gross_r"),
                      "SELL_net_expectancy_95_ci": _block_bootstrap_expectancy_ci(sides["SELL"], "net_r"),
                      "combined_gross_expectancy_95_ci": _block_bootstrap_expectancy_ci(trades, "gross_r"),
                      "combined_net_expectancy_95_ci": _block_bootstrap_expectancy_ci(trades, "net_r"),
                  },
                  "plans": result["plans"], "outcomes": trades}
        if scenarios:
            period["cost_sensitivity"] = {}
            for label, cost in scenarios.items():
                adjusted = [{**r, "net_r": r["gross_r"] - cost / r["plan"]["risk_price"]} for r in trades]
                period["cost_sensitivity"][label] = {
                    "BUY": _stats([r for r in adjusted if r["plan"]["side"] == "BUY"], True),
                    "SELL": _stats([r for r in adjusted if r["plan"]["side"] == "SELL"], True),
                    "combined": _stats(adjusted, True)}
        periods[name] = period
    return {"status": "complete", "candidate_version": candidate_version, "dataset_fingerprint": fingerprint,
            "candle_payload_sha256": candle_payload_sha256,
            "evaluation_mode": evaluation_mode, "split_indices_half_open": splits, "embargo_bars_each_side": EMBARGO_BARS,
            "periods": periods, "final_test": "SEALED_NOT_RUN" if "final_test" not in periods else periods["final_test"],
            "cost_model": {"round_trip_cost_price_units": round_trip_cost_price_units,
                           "cost_status": "assumption_not_broker_calibrated" if round_trip_cost_price_units is not None else "uncalibrated_gross_only",
                           "cost_sensitivity": scenarios},
            "no_trade_baseline": {"trades": 0, "net_r": 0.0, "exposure": 0.0},
            "execution_enabled": False,
            "limitations": ["OHLC sweep/reclaim is a price-action proxy, not proof of institutional order flow.",
                            "OHLC replay is not bid/ask tick execution evidence.",
                            "H1 context is descriptive only and never vetoes a signal.",
                            "Costs are price-unit assumptions, not broker-calibrated."]}
