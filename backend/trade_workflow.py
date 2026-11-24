"""Research-only trade-plan and independent risk-gate contracts.

These pure functions do not fetch data, size broker lots, or place orders.
They require a completed-candle confirmation and fail closed on invalid or
stale inputs. Broker-feed verification is required for a risk-gate PASS.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any


SUPPORTED_SYMBOLS = {"XAUUSD", "EURUSD"}
SUPPORTED_TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}


def _finite_positive(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite positive number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be a finite positive number.") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a finite positive number.")
    return number


def _finite_non_negative(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be a finite non-negative number.") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a finite non-negative number.")
    return number


def _timestamp(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a Unix timestamp in seconds.")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be a Unix timestamp in seconds.") from None
    if number <= 0 or number != value:
        raise ValueError(f"{field} must be a Unix timestamp in seconds.")
    return number


def build_trade_plan(
    candidate: dict[str, Any],
    *,
    now: int | None = None,
    max_candle_age_seconds: int = 3600,
) -> dict[str, Any]:
    """Validate a completed-candle candidate and produce a reproducible plan.

    Required candidate fields:
      symbol, side, timeframe, strategy_id, strategy_version, data_source,
      broker_feed_verified, instrument_enabled, candle_closed,
      trigger_confirmed, candle_close_time, decision_time, expiry_time,
      entry_price, stop_price, target_price, risk_pct.

    `round_trip_cost_price` is an optional price-unit estimate covering the
    expected round-trip spread/commission/slippage/financing cost. It must be
    supplied by a trusted instrument-specific evaluator before a plan can
    pass the independent risk gate.
    """
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object.")
    current_time = int(time.time()) if now is None else _timestamp(now, "now")
    if isinstance(max_candle_age_seconds, bool) or not isinstance(max_candle_age_seconds, int) or max_candle_age_seconds < 1:
        raise ValueError("max_candle_age_seconds must be a positive integer.")

    symbol = str(candidate.get("symbol", "")).strip().upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError("Unsupported instrument. Use XAUUSD or EURUSD.")
    if symbol == "EURUSD" and candidate.get("instrument_enabled") is not True:
        raise ValueError("EURUSD is disabled until its feed and broker symbol metadata are verified.")
    if candidate.get("instrument_enabled") is not True:
        raise ValueError(f"{symbol} is not enabled for research candidates.")

    side = str(candidate.get("side", "")).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL.")
    timeframe = str(candidate.get("timeframe", "")).strip().upper()
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError("Unsupported timeframe.")

    strategy_id = str(candidate.get("strategy_id", "")).strip()
    strategy_version = str(candidate.get("strategy_version", "")).strip()
    data_source = str(candidate.get("data_source", "")).strip()
    if not strategy_id or not strategy_version or not data_source:
        raise ValueError("strategy_id, strategy_version and data_source are required.")

    if candidate.get("candle_closed") is not True:
        raise ValueError("The signal candle must be fully closed.")
    if candidate.get("trigger_confirmed") is not True:
        raise ValueError("The entry trigger has not been confirmed by a completed candle.")

    candle_close_time = _timestamp(candidate.get("candle_close_time"), "candle_close_time")
    decision_time = _timestamp(candidate.get("decision_time"), "decision_time")
    expiry_time = _timestamp(candidate.get("expiry_time"), "expiry_time")
    if candle_close_time > decision_time:
        raise ValueError("decision_time cannot precede the signal candle close.")
    if decision_time > current_time or candle_close_time > current_time:
        raise ValueError("Future-dated candle or decision timestamps are not allowed.")
    if current_time - candle_close_time > max_candle_age_seconds:
        raise ValueError("The signal candle is stale.")
    if expiry_time <= decision_time:
        raise ValueError("expiry_time must be later than decision_time.")

    entry = _finite_positive(candidate.get("entry_price"), "entry_price")
    stop = _finite_positive(candidate.get("stop_price"), "stop_price")
    target = _finite_positive(candidate.get("target_price"), "target_price")
    risk_pct = _finite_positive(candidate.get("risk_pct"), "risk_pct")
    if risk_pct > 100:
        raise ValueError("risk_pct cannot exceed 100.")
    cost = _finite_non_negative(candidate.get("round_trip_cost_price", 0), "round_trip_cost_price")

    if side == "BUY":
        if not stop < entry < target:
            raise ValueError("For BUY, prices must satisfy stop < entry < target.")
        risk_distance = entry - stop
        reward_distance = target - entry
    else:
        if not target < entry < stop:
            raise ValueError("For SELL, prices must satisfy target < entry < stop.")
        risk_distance = stop - entry
        reward_distance = entry - target

    reward_risk = reward_distance / risk_distance
    net_reward = reward_distance - cost
    net_risk = risk_distance + cost
    net_reward_risk = net_reward / net_risk

    fingerprint_fields = {
        "symbol": symbol,
        "side": side,
        "timeframe": timeframe,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "data_source": data_source,
        "candle_close_time": candle_close_time,
        "decision_time": decision_time,
        "expiry_time": expiry_time,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "risk_pct": risk_pct,
        "round_trip_cost_price": cost,
    }
    canonical = json.dumps(fingerprint_fields, sort_keys=True, separators=(",", ":"))
    plan_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]

    return {
        "plan_id": plan_id,
        **fingerprint_fields,
        "broker_feed_verified": candidate.get("broker_feed_verified") is True,
        "candle_closed": True,
        "trigger_confirmed": True,
        "gross_reward_risk": round(reward_risk, 6),
        "net_reward_risk": round(net_reward_risk, 6),
        "status": "RESEARCH_CANDIDATE",
        "research_only": True,
        "execution_enabled": False,
    }


def evaluate_risk_gate(
    plan: dict[str, Any],
    limits: dict[str, Any],
    daily_state: dict[str, Any] | None = None,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Apply an independent fail-closed risk gate; never submits an order.

    Required limits: max_risk_pct_per_trade, max_daily_risk_pct,
    min_net_reward_risk, max_trades_per_day.
    Required daily_state: risk_used_pct and trades_taken (defaults to zero).
    """
    if not isinstance(plan, dict) or not isinstance(limits, dict):
        raise ValueError("plan and limits must be objects.")
    state = daily_state or {}
    current_time = int(time.time()) if now is None else _timestamp(now, "now")
    reasons: list[str] = []

    required_limits = (
        "max_risk_pct_per_trade",
        "max_daily_risk_pct",
        "min_net_reward_risk",
        "max_trades_per_day",
    )
    if any(key not in limits for key in required_limits):
        raise ValueError("All risk limits must be explicitly configured.")

    max_trade_risk = _finite_positive(limits["max_risk_pct_per_trade"], "max_risk_pct_per_trade")
    max_daily_risk = _finite_positive(limits["max_daily_risk_pct"], "max_daily_risk_pct")
    min_net_rr = _finite_positive(limits["min_net_reward_risk"], "min_net_reward_risk")
    max_trades = limits["max_trades_per_day"]
    if isinstance(max_trades, bool) or not isinstance(max_trades, int) or max_trades < 1:
        raise ValueError("max_trades_per_day must be a positive integer.")

    risk_used = _finite_non_negative(state.get("risk_used_pct", 0), "risk_used_pct")
    trades_taken = state.get("trades_taken", 0)
    if isinstance(trades_taken, bool) or not isinstance(trades_taken, int) or trades_taken < 0:
        raise ValueError("trades_taken must be a non-negative integer.")

    plan_risk = _finite_positive(plan.get("risk_pct"), "plan.risk_pct")
    plan_expiry = _timestamp(plan.get("expiry_time"), "plan.expiry_time")
    plan_rr = _finite_positive(plan.get("net_reward_risk"), "plan.net_reward_risk")

    if plan.get("research_only") is not True or plan.get("execution_enabled") is not False:
        reasons.append("Plan must remain explicitly research-only.")
    if plan.get("broker_feed_verified") is not True:
        reasons.append("Verified broker candles are required; reference-feed plans cannot pass this gate.")
    if plan_expiry <= current_time:
        reasons.append("The trade plan has expired.")
    if plan_risk > max_trade_risk:
        reasons.append("Per-trade risk exceeds the configured limit.")
    if risk_used + plan_risk > max_daily_risk:
        reasons.append("The trade would exceed the configured daily risk limit.")
    if trades_taken >= max_trades:
        reasons.append("The daily trade-count limit has been reached.")
    if plan_rr < min_net_rr:
        reasons.append("Net reward:risk is below the configured minimum.")

    return {
        "status": "BLOCK" if reasons else "PASS",
        "plan_id": plan.get("plan_id"),
        "reasons": reasons,
        "risk_used_pct": round(risk_used, 6),
        "proposed_risk_pct": round(plan_risk, 6),
        "projected_daily_risk_pct": round(risk_used + plan_risk, 6),
        "research_only": True,
        "order_submitted": False,
    }
