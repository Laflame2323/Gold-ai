"""Deterministic, bid/ask-aware replay of one research trade plan.

The simulator is deliberately separate from signal generation and never
places orders. BUY positions enter on ASK and exit on BID; SELL positions
enter on BID and exit on ASK. If one OHLC bar touches both stop and target,
the stop is assumed first. This is conservative, not tick-accurate.
"""
from __future__ import annotations

import math
from typing import Any


def _price(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite positive price.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a finite positive price.") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be a finite positive price.")
    return result


def _stamp(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive Unix timestamp in seconds.")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a positive Unix timestamp in seconds.") from None
    if result <= 0 or result != value:
        raise ValueError(f"{label} must be a positive Unix timestamp in seconds.")
    return result


def _validate_candles(candles, label):
    if not isinstance(candles, list) or not candles:
        raise ValueError(f"{label} candles must be a non-empty list.")
    output = []
    previous = None
    for row in candles:
        if not isinstance(row, dict):
            raise ValueError(f"Each {label} candle must be an object.")
        stamp = _stamp(row.get("time", row.get("timestamp")), f"{label}.time")
        values = {
            field: _price(row.get(field), f"{label}.{field}")
            for field in ("open", "high", "low", "close")
        }
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"{label} candle has inconsistent high/low values.")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"{label} candle has inconsistent high/low values.")
        if previous is not None and stamp <= previous:
            raise ValueError(f"{label} candle timestamps must be strictly increasing.")
        previous = stamp
        output.append({"time": stamp, **values})
    return output


def split_bid_ask_rows(rows):
    """Convert Dukascopy-style merged rows into paired OHLC candle lists."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a list.")
    bid, ask = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each merged bid/ask row must be an object.")
        stamp = _stamp(row.get("timestamp"), "timestamp")
        bid.append({
            "time": stamp,
            **{field: row.get(f"bid_{field}") for field in ("open", "high", "low", "close")},
        })
        ask.append({
            "time": stamp,
            **{field: row.get(f"ask_{field}") for field in ("open", "high", "low", "close")},
        })
    return bid, ask


def simulate_trade_plan(
    plan: dict[str, Any],
    bid_candles,
    ask_candles,
    *,
    timeframe_seconds: int = 60,
    extra_cost_price: float = 0.0,
) -> dict[str, Any]:
    """Replay one plan against paired bid/ask OHLC bars in chronological order.

    `extra_cost_price` is the round-trip commission plus slippage in price
    units. Spread is already represented by the side-correct entry/exit prices
    and must not be deducted a second time.
    """
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object.")
    if isinstance(timeframe_seconds, bool) or not isinstance(timeframe_seconds, int) or timeframe_seconds < 1:
        raise ValueError("timeframe_seconds must be a positive integer.")
    extra_cost = float(extra_cost_price)
    if not math.isfinite(extra_cost) or extra_cost < 0:
        raise ValueError("extra_cost_price must be finite and non-negative.")

    bid = _validate_candles(bid_candles, "bid")
    ask = _validate_candles(ask_candles, "ask")
    if len(bid) != len(ask) or any(b["time"] != a["time"] for b, a in zip(bid, ask)):
        raise ValueError("Bid and ask candles must have identical timestamps and counts.")
    for b, a in zip(bid, ask):
        if any(a[field] < b[field] for field in ("open", "high", "low", "close")):
            raise ValueError("Ask OHLC prices must not be below corresponding bid prices.")

    side = str(plan.get("side", "")).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("plan.side must be BUY or SELL.")
    sign = 1 if side == "BUY" else -1
    decision_time = _stamp(plan.get("decision_time"), "plan.decision_time")
    expiry_time = _stamp(plan.get("expiry_time"), "plan.expiry_time")
    if expiry_time <= decision_time:
        raise ValueError("plan.expiry_time must be later than decision_time.")
    planned_entry = _price(plan.get("entry_price"), "plan.entry_price")
    stop = _price(plan.get("stop_price"), "plan.stop_price")
    target = _price(plan.get("target_price"), "plan.target_price")
    if (side == "BUY" and not stop < planned_entry < target) or (
        side == "SELL" and not target < planned_entry < stop
    ):
        raise ValueError("Plan stop, entry and target are inconsistent with its direction.")

    entry_index = next(
        (index for index, candle in enumerate(bid)
         if candle["time"] >= decision_time and candle["time"] + timeframe_seconds <= expiry_time),
        None,
    )
    if entry_index is None:
        return {
            "status": "no_entry",
            "reason": "No complete candle is available after the decision and before plan expiry.",
            "plan_id": plan.get("plan_id"),
            "research_only": True,
            "execution_enabled": False,
        }

    entry_bar = bid[entry_index]
    actual_entry = ask[entry_index]["open"] if side == "BUY" else entry_bar["open"]
    if (side == "BUY" and not stop < actual_entry < target) or (
        side == "SELL" and not target < actual_entry < stop
    ):
        return {
            "status": "no_entry",
            "reason": "The next-bar opening price has invalidated the planned entry, stop or target; do not chase.",
            "plan_id": plan.get("plan_id"),
            "planned_entry": planned_entry,
            "actual_open": round(actual_entry, 8),
            "research_only": True,
            "execution_enabled": False,
        }

    risk_distance = abs(actual_entry - stop)
    exit_rows = bid if side == "BUY" else ask
    exit_price = None
    exit_index = None
    exit_reason = None
    last_eligible_index = entry_index - 1

    for index in range(entry_index, len(bid)):
        candle = exit_rows[index]
        bar_end = candle["time"] + timeframe_seconds
        if bar_end > expiry_time:
            break
        last_eligible_index = index
        opening = candle["open"]

        stop_gap = opening <= stop if side == "BUY" else opening >= stop
        target_gap = opening >= target if side == "BUY" else opening <= target
        if stop_gap:
            exit_price, exit_index, exit_reason = opening, index, "stop_gap"
            break
        if target_gap:
            exit_price, exit_index, exit_reason = opening, index, "target_gap"
            break

        stop_hit = candle["low"] <= stop if side == "BUY" else candle["high"] >= stop
        target_hit = candle["high"] >= target if side == "BUY" else candle["low"] <= target
        if stop_hit:
            exit_price, exit_index, exit_reason = stop, index, "stop"
            break
        if target_hit:
            exit_price, exit_index, exit_reason = target, index, "target"
            break

    if exit_index is None:
        if last_eligible_index < entry_index:
            return {
                "status": "no_entry",
                "reason": "No complete post-decision candle fits before plan expiry.",
                "plan_id": plan.get("plan_id"),
                "research_only": True,
                "execution_enabled": False,
            }
        exit_index = last_eligible_index
        exit_price = exit_rows[exit_index]["close"]
        exit_reason = "time_expiry" if exit_rows[exit_index]["time"] + timeframe_seconds == expiry_time else "data_end"

    gross_pnl = sign * (exit_price - actual_entry)
    gross_r = gross_pnl / risk_distance
    net_r = (gross_pnl - extra_cost) / risk_distance
    entry_spread = ask[entry_index]["open"] - bid[entry_index]["open"]
    exit_spread = ask[exit_index]["close"] - bid[exit_index]["close"]

    return {
        "status": "complete",
        "plan_id": plan.get("plan_id"),
        "symbol": plan.get("symbol"),
        "side": side,
        "entry_time": entry_bar["time"],
        "exit_time": exit_rows[exit_index]["time"] + timeframe_seconds,
        "planned_entry": round(planned_entry, 8),
        "actual_entry": round(actual_entry, 8),
        "stop_price": round(stop, 8),
        "target_price": round(target, 8),
        "actual_exit": round(exit_price, 8),
        "exit_reason": exit_reason,
        "risk_distance": round(risk_distance, 8),
        "entry_spread": round(entry_spread, 8),
        "exit_spread": round(exit_spread, 8),
        "extra_cost_price": round(extra_cost, 8),
        "gross_r": round(gross_r, 6),
        "net_r": round(net_r, 6),
        "research_only": True,
        "execution_enabled": False,
        "limitations": [
            "OHLC bars do not reveal the exact intrabar path; if stop and target both trade in one bar, stop is assumed first.",
            "Spread is reflected by side-correct bid/ask fills; extra_cost_price should include commission and slippage only.",
            "This replay is historical analysis, not a forecast or guarantee of future fills.",
        ],
    }
