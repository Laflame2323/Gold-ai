"""Isolated M15 VWAP/EMA strategy research. No order execution."""
from __future__ import annotations

import math
from datetime import datetime, timezone


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for item in values[period:]:
        value += alpha * (item - value)
    return value


def _rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    gain = sum(gains[:period]) / period
    loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        gain = (gain * (period - 1) + gains[i]) / period
        loss = (loss * (period - 1) + losses[i]) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _atr_adx(candles, period=14):
    if len(candles) <= period:
        return None, None
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        up = cur["high"] - prev["high"]
        down = prev["low"] - cur["low"]
        trs.append(max(cur["high"] - cur["low"],
                       abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr = sum(trs[:period]) / period
    p = sum(plus_dm[:period]) / period
    m = sum(minus_dm[:period]) / period
    dx = []
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        p = (p * (period - 1) + plus_dm[i]) / period
        m = (m * (period - 1) + minus_dm[i]) / period
        if atr <= 0:
            dx.append(0.0)
        else:
            pdi, mdi = 100 * p / atr, 100 * m / atr
            dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    if not dx:
        return atr, None
    adx = sum(dx[:period]) / period if len(dx) >= period else sum(dx) / len(dx)
    for value in dx[period:]:
        adx = (adx * (period - 1) + value) / period
    return atr, adx


def _vwap(candles):
    """UTC-session VWAP; returns None if any required volume is unavailable."""
    if not candles or any(c.get("volume") is None for c in candles):
        return None
    total_pv = total_volume = 0.0
    active_day = None
    result = []
    for candle in candles:
        day = datetime.fromtimestamp(candle["time"], timezone.utc).date()
        if day != active_day:
            active_day, total_pv, total_volume = day, 0.0, 0.0
        volume = float(candle["volume"])
        if not math.isfinite(volume) or volume < 0:
            return None
        typical = (candle["high"] + candle["low"] + candle["close"]) / 3.0
        total_pv += typical * volume
        total_volume += volume
        result.append(total_pv / total_volume if total_volume > 0 else None)
    return result


def _validate(candles):
    if not isinstance(candles, list):
        raise ValueError("candles must be a list")
    rows, previous = [], None
    for c in candles:
        try:
            row = {k: float(c[k]) for k in ("open", "high", "low", "close")}
            row["time"] = int(c["time"])
            row["volume"] = None if c.get("volume") is None else float(c["volume"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Each candle needs valid time, OHLC and volume fields.")
        if previous is not None and row["time"] <= previous:
            raise ValueError("Candles must be ordered by increasing time.")
        previous = row["time"]
        if not all(math.isfinite(row[k]) and row[k] > 0 for k in ("open", "high", "low", "close")):
            raise ValueError("OHLC prices must be finite and positive.")
        if row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(row["open"], row["close"], row["high"]):
            raise ValueError("Candle OHLC values are inconsistent.")
        if row["volume"] is not None and (not math.isfinite(row["volume"]) or row["volume"] < 0):
            raise ValueError("Volume must be finite and non-negative.")
        rows.append(row)
    return rows


def run_vwap_strategy_lab(candles, horizon=5, minimum_samples=100,
                          adx_threshold=20.0, stop_atr=1.5,
                          spread_price=0.0, slippage_price=0.0,
                          volume_kind="unknown"):
    """Test fixed VWAP + EMA50/200 + RSI/ADX rules with next-open entries."""
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 100:
        raise ValueError("horizon must be an integer between 1 and 100")
    if isinstance(minimum_samples, bool) or not isinstance(minimum_samples, int) or minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")
    for name, value in (("adx_threshold", adx_threshold), ("stop_atr", stop_atr),
                        ("spread_price", spread_price), ("slippage_price", slippage_price)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative number")
    rows = _validate(candles)
    if len(rows) < 201 + minimum_samples + horizon:
        return {"status": "insufficient_data", "candle_count": len(rows),
                "required_candle_count": 201 + minimum_samples + horizon,
                "read_only": True, "execution_enabled": False}
    if any(row["volume"] is None for row in rows):
        return {"status": "volume_unavailable", "candle_count": len(rows),
                "message": "VWAP was not calculated because one or more candles lack volume.",
                "read_only": True, "execution_enabled": False}
    closes = [r["close"] for r in rows]
    vwap = _vwap(rows)
    if vwap is None or not any(x is not None for x in vwap):
        return {"status": "volume_unavailable", "message": "No positive cumulative volume is available.",
                "read_only": True, "execution_enabled": False}

    trades = []
    start = 200
    for i in range(start, len(rows) - horizon):
        prefix = rows[:i + 1]
        ema50, ema200 = _ema(closes[:i + 1], 50), _ema(closes[:i + 1], 200)
        rsi = _rsi(closes[:i + 1])
        atr, adx = _atr_adx(prefix)
        if None in (ema50, ema200, rsi, atr, adx) or vwap[i] is None or atr <= 0:
            continue
        signal = "WAIT"
        if closes[i] > vwap[i] and ema50 > ema200 and rsi >= 50 and rsi <= 70 and adx >= adx_threshold:
            signal = "BUY"
        elif closes[i] < vwap[i] and ema50 < ema200 and rsi <= 50 and rsi >= 30 and adx >= adx_threshold:
            signal = "SELL"
        if signal == "WAIT":
            continue
        entry_i = i + 1
        entry = rows[entry_i]["open"]
        stop = entry - stop_atr * atr if signal == "BUY" else entry + stop_atr * atr
        exit_i, exit_price, exit_reason = min(i + horizon, len(rows) - 1), rows[min(i + horizon, len(rows) - 1)]["close"], "time"
        for j in range(entry_i, min(i + horizon, len(rows) - 1) + 1):
            hit = rows[j]["low"] <= stop if signal == "BUY" else rows[j]["high"] >= stop
            if hit:
                # Model adverse gaps through the stop instead of granting a
                # fill at a price the market may have skipped.
                gap_fill = min(stop, rows[j]["open"]) if signal == "BUY" else max(stop, rows[j]["open"])
                exit_i, exit_price, exit_reason = j, gap_fill, "atr_stop"
                break
        gross = (exit_price - entry) if signal == "BUY" else (entry - exit_price)
        net = gross - spread_price - 2.0 * slippage_price
        trades.append({"signal": signal, "entry_time": rows[entry_i]["time"],
                       "exit_time": rows[exit_i]["time"], "entry_price": entry,
                       "exit_price": exit_price, "exit_reason": exit_reason,
                       "net_price_pnl": net, "win": net > 0})
    wins = sum(t["win"] for t in trades)
    pnls = [t["net_price_pnl"] for t in trades]
    gains = sum(x for x in pnls if x > 0)
    losses = -sum(x for x in pnls if x < 0)
    def side(name):
        subset = [t for t in trades if t["signal"] == name]
        return {"trades": len(subset), "win_rate_pct": round(100 * sum(t["win"] for t in subset) / len(subset), 2) if subset else None,
                "average_net_price_pnl": round(sum(t["net_price_pnl"] for t in subset) / len(subset), 5) if subset else None}
    return {
        "status": "complete", "strategy": "VWAP + EMA50/EMA200 + RSI14 + ADX14; ATR stop",
        "candle_count": len(rows), "signals_tested": len(trades),
        "buy": side("BUY"), "sell": side("SELL"),
        "win_rate_pct": round(100 * wins / len(trades), 2) if trades else None,
        "average_net_price_pnl": round(sum(pnls) / len(pnls), 5) if pnls else None,
        "profit_factor": round(gains / losses, 3) if losses else (None if not gains else "infinite"),
        "volume_kind": volume_kind, "vwap_session_timezone": "UTC",
        "cost_assumptions": {"spread_price_round_trip": spread_price,
                             "slippage_price_per_side": slippage_price},
        "stop_rule": f"{stop_atr} x ATR(14); stop checked before time exit",
        "horizon_candles": horizon, "trades": trades,
        "limitations": ["Research-only; no orders are placed.",
                        "MT5 candle volume is tick volume, not exchange-traded volume.",
                        "OHLC stop simulation cannot reconstruct intrabar price path.",
                        "Spread/slippage inputs are user-supplied assumptions; defaults are zero.",
                        "No commission, swap, latency or broker execution simulation.",
                        "Historical performance does not guarantee future results."],
        "read_only": True, "execution_enabled": False,
    }
