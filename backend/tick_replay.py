"""Tick-accurate bid/ask replay for Gold AI research plans.

This module consumes archived broker quote ticks only. It never places orders.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite positive number.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a finite positive number.") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be a finite positive number.")
    return result


def _timestamp(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive Unix timestamp in seconds.")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a positive Unix timestamp in seconds.") from None
    if result <= 0 or result != value:
        raise ValueError(f"{label} must be a positive Unix timestamp in seconds.")
    return result


def _validate_ticks(ticks):
    if not isinstance(ticks, list) or not ticks:
        raise ValueError("ticks must be a non-empty list.")
    normalized = []
    previous = None
    for row in ticks:
        if not isinstance(row, dict):
            raise ValueError("Each tick must be an object.")
        stamp = _timestamp(row.get("time_msc"), "tick.time_msc")
        bid = _number(row.get("bid"), "tick.bid")
        ask = _number(row.get("ask"), "tick.ask")
        if ask < bid:
            raise ValueError("Tick ask cannot be below bid.")
        identity = (stamp, int(row.get("id", 0)))
        if previous is not None and identity < previous:
            raise ValueError("Ticks must be ordered by timestamp and archive id.")
        previous = identity
        normalized.append({"time_msc": stamp, "bid": bid, "ask": ask})
    return normalized


def simulate_trade_plan_on_ticks(
    plan: dict[str, Any],
    ticks,
    *,
    extra_cost_price: float = 0.0,
) -> dict[str, Any]:
    """Replay a plan against actual archived bid/ask quote ticks.

    BUY entries use ask and exits use bid. SELL entries use bid and exits use
    ask. Stops and targets are checked against every quote, avoiding OHLC
    assumptions about which level traded first.
    """
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object.")
    side = str(plan.get("side", "")).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("plan.side must be BUY or SELL.")
    sign = 1 if side == "BUY" else -1
    decision = _timestamp(plan.get("decision_time"), "plan.decision_time") * 1000
    expiry = _timestamp(plan.get("expiry_time"), "plan.expiry_time") * 1000
    if expiry <= decision:
        raise ValueError("plan.expiry_time must be later than decision_time.")
    planned_entry = _number(plan.get("entry_price"), "plan.entry_price")
    stop = _number(plan.get("stop_price"), "plan.stop_price")
    target = _number(plan.get("target_price"), "plan.target_price")
    if (side == "BUY" and not stop < planned_entry < target) or (
        side == "SELL" and not target < planned_entry < stop
    ):
        raise ValueError("Plan stop, entry and target are inconsistent with its direction.")
    if isinstance(extra_cost_price, bool):
        raise ValueError("extra_cost_price must be finite and non-negative.")
    extra_cost = float(extra_cost_price)
    if not math.isfinite(extra_cost) or extra_cost < 0:
        raise ValueError("extra_cost_price must be finite and non-negative.")

    normalized = _validate_ticks(ticks)
    eligible = [
        (index, tick) for index, tick in enumerate(normalized)
        if decision <= tick["time_msc"] < expiry
    ]
    if not eligible:
        return {
            "status": "no_entry",
            "reason": "No valid broker bid/ask tick exists after the decision and before expiry.",
            "plan_id": plan.get("plan_id"),
            "research_only": True,
            "execution_enabled": False,
        }

    entry_index, entry_tick = eligible[0]
    actual_entry = entry_tick["ask"] if side == "BUY" else entry_tick["bid"]
    if (side == "BUY" and not stop < actual_entry < target) or (
        side == "SELL" and not target < actual_entry < stop
    ):
        return {
            "status": "no_entry",
            "reason": "The first available quote invalidated the planned entry; do not chase.",
            "plan_id": plan.get("plan_id"),
            "planned_entry": planned_entry,
            "actual_entry": round(actual_entry, 8),
            "research_only": True,
            "execution_enabled": False,
        }

    exit_index = entry_index
    exit_price = entry_tick["bid"] if side == "BUY" else entry_tick["ask"]
    exit_reason = None
    for index, tick in eligible:
        if index < entry_index:
            continue
        exit_quote = tick["bid"] if side == "BUY" else tick["ask"]
        stop_hit = exit_quote <= stop if side == "BUY" else exit_quote >= stop
        target_hit = exit_quote >= target if side == "BUY" else exit_quote <= target
        if stop_hit:
            exit_index, exit_price, exit_reason = index, exit_quote, "stop"
            break
        if target_hit:
            exit_index, exit_price, exit_reason = index, exit_quote, "target"
            break

    if exit_reason is None:
        exit_index, last_tick = eligible[-1]
        exit_price = last_tick["bid"] if side == "BUY" else last_tick["ask"]
        exit_reason = "time_expiry" if last_tick["time_msc"] >= expiry - 1 else "data_end"

    risk_distance = abs(actual_entry - stop)
    gross_pnl = sign * (exit_price - actual_entry)
    gross_r = gross_pnl / risk_distance
    net_r = (gross_pnl - extra_cost) / risk_distance
    return {
        "status": "complete",
        "plan_id": plan.get("plan_id"),
        "symbol": plan.get("symbol"),
        "side": side,
        "entry_time_msc": entry_tick["time_msc"],
        "exit_time_msc": normalized[exit_index]["time_msc"],
        "planned_entry": round(planned_entry, 8),
        "actual_entry": round(actual_entry, 8),
        "stop_price": round(stop, 8),
        "target_price": round(target, 8),
        "actual_exit": round(exit_price, 8),
        "exit_reason": exit_reason,
        "risk_distance": round(risk_distance, 8),
        "entry_spread": round(entry_tick["ask"] - entry_tick["bid"], 8),
        "exit_spread": round(normalized[exit_index]["ask"] - normalized[exit_index]["bid"], 8),
        "extra_cost_price": round(extra_cost, 8),
        "gross_r": round(gross_r, 6),
        "net_r": round(net_r, 6),
        "tick_count_used": exit_index - entry_index + 1,
        "research_only": True,
        "execution_enabled": False,
        "limitations": [
            "Historical broker quotes are not a guarantee of future execution or liquidity.",
            "Commission and slippage must be supplied separately; spread is already reflected in bid/ask fills.",
            "The result is a replay of a supplied plan, not evidence that the signal itself is profitable.",
        ],
    }
