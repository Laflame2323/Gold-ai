"""Isolated M15 VWAP/EMA strategy research. No order execution."""
from __future__ import annotations

import math
from datetime import datetime, timezone


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


def _rsi_series(values, period=14):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = sum(max(x, 0.0) for x in changes[:period]) / period
    loss = sum(max(-x, 0.0) for x in changes[:period]) / period
    def value(g, l):
        if l == 0:
            return 100.0 if g else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)
    out[period] = value(gain, loss)
    for i in range(period + 1, len(values)):
        change = changes[i - 1]
        gain = (gain * (period - 1) + max(change, 0.0)) / period
        loss = (loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = value(gain, loss)
    return out


def _atr_adx_series(candles, period=14):
    n = len(candles)
    atrs, adxs = [None] * n, [None] * n
    trs, plus_dm, minus_dm = [0.0] * n, [0.0] * n, [0.0] * n
    for i in range(1, n):
        cur, prev = candles[i], candles[i - 1]
        up, down = cur["high"] - prev["high"], prev["low"] - cur["low"]
        trs[i] = max(cur["high"] - cur["low"],
                     abs(cur["high"] - prev["close"]),
                     abs(cur["low"] - prev["close"]))
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
    if n <= period:
        return atrs, adxs
    atr = sum(trs[1:period + 1]) / period
    plus = sum(plus_dm[1:period + 1]) / period
    minus = sum(minus_dm[1:period + 1]) / period
    dx_values = []
    for i in range(period, n):
        if i > period:
            atr = (atr * (period - 1) + trs[i]) / period
            plus = (plus * (period - 1) + plus_dm[i]) / period
            minus = (minus * (period - 1) + minus_dm[i]) / period
        atrs[i] = atr
        if atr > 0:
            pdi, mdi = 100 * plus / atr, 100 * minus / atr
            dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0
        else:
            dx = 0.0
        dx_values.append(dx)
        if len(dx_values) == period:
            adx = sum(dx_values) / period
            adxs[i] = adx
        elif len(dx_values) > period:
            adx = (adx * (period - 1) + dx) / period
            adxs[i] = adx
    return atrs, adxs


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
    required = 201 + minimum_samples + horizon
    if len(rows) < required:
        return {"status": "insufficient_data", "candle_count": len(rows),
                "required_candle_count": required,
                "read_only": True, "execution_enabled": False}
    if any(row["volume"] is None for row in rows):
        return {"status": "volume_unavailable", "candle_count": len(rows),
                "message": "VWAP was not calculated because one or more candles lack volume.",
                "read_only": True, "execution_enabled": False}
    vwap = _vwap(rows)
    if vwap is None or not any(x is not None for x in vwap):
        return {"status": "volume_unavailable", "message": "No positive cumulative volume is available.",
                "read_only": True, "execution_enabled": False}

    closes = [r["close"] for r in rows]
    ema50, ema200 = _ema_series(closes, 50), _ema_series(closes, 200)
    rsi = _rsi_series(closes)
    atr, adx = _atr_adx_series(rows)
    trades = []
    for i in range(200, len(rows) - horizon):
        if any(series[i] is None for series in (ema50, ema200, rsi, atr, adx)) or vwap[i] is None or atr[i] <= 0:
            continue
        signal = "WAIT"
        if closes[i] > vwap[i] and ema50[i] > ema200[i] and 50 <= rsi[i] <= 70 and adx[i] >= adx_threshold:
            signal = "BUY"
        elif closes[i] < vwap[i] and ema50[i] < ema200[i] and 30 <= rsi[i] <= 50 and adx[i] >= adx_threshold:
            signal = "SELL"
        if signal == "WAIT":
            continue
        entry_i = i + 1
        entry = rows[entry_i]["open"]
        stop = entry - stop_atr * atr[i] if signal == "BUY" else entry + stop_atr * atr[i]
        exit_i = i + horizon
        exit_price, exit_reason = rows[exit_i]["close"], "time"
        for j in range(entry_i, exit_i + 1):
            hit = rows[j]["low"] <= stop if signal == "BUY" else rows[j]["high"] >= stop
            if hit:
                # Adverse gaps through the stop are filled at the open, not the skipped stop price.
                exit_price = min(stop, rows[j]["open"]) if signal == "BUY" else max(stop, rows[j]["open"])
                exit_i, exit_reason = j, "atr_stop"
                break
        gross = (exit_price - entry) if signal == "BUY" else (entry - exit_price)
        net = gross - spread_price - 2.0 * slippage_price
        trades.append({"signal": signal, "decision_index": i,
                       "entry_time": rows[entry_i]["time"], "exit_time": rows[exit_i]["time"],
                       "entry_price": entry, "exit_price": exit_price,
                       "exit_reason": exit_reason, "net_price_pnl": net, "win": net > 0})

    def summarize(subset):
        pnls = [t["net_price_pnl"] for t in subset]
        wins = sum(t["win"] for t in subset)
        gross_win = sum(x for x in pnls if x > 0)
        gross_loss = -sum(x for x in pnls if x < 0)
        equity = peak = max_drawdown = 0.0
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        return {
            "trades": len(subset),
            "win_rate_pct": round(100 * wins / len(subset), 2) if subset else None,
            "average_net_price_pnl": round(sum(pnls) / len(pnls), 5) if subset else None,
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else (None if not gross_win else "infinite"),
            "max_drawdown_price": round(max_drawdown, 5),
        }

    buys = [t for t in trades if t["signal"] == "BUY"]
    sells = [t for t in trades if t["signal"] == "SELL"]
    independent, next_allowed = [], 200
    for trade in trades:
        if trade["decision_index"] >= next_allowed:
            independent.append(trade)
            next_allowed = trade["decision_index"] + horizon
    return {
        "status": "complete", "strategy": "VWAP + EMA50/EMA200 + RSI14 + ADX14; ATR stop",
        "candle_count": len(rows), "signals_tested": len(trades),
        **summarize(trades), "buy": summarize(buys), "sell": summarize(sells),
        "non_overlapping_check": summarize(independent),
        "volume_kind": volume_kind, "vwap_session_timezone": "UTC",
        "cost_assumptions": {"spread_price_round_trip": spread_price,
                             "slippage_price_per_side": slippage_price},
        "stop_rule": f"{stop_atr} x ATR(14); adverse gap fills modelled; stop checked before time exit",
        "horizon_candles": horizon, "trades": trades,
        "limitations": ["Research-only; no orders are placed.",
                        "MT5 candle volume is tick volume, not exchange-traded volume.",
                        "OHLC stop simulation cannot reconstruct intrabar price path.",
                        "Spread/slippage inputs are user-supplied assumptions; defaults are zero.",
                        "No commission, swap, latency or broker execution simulation.",
                        "Drawdown is in price units, not account-currency or percentage equity.",
                        "Historical performance does not guarantee future results."],
        "read_only": True, "execution_enabled": False,
    }
