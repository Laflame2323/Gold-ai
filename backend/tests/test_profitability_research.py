import math
import pytest

import profitability_research as base_research
import bid_ask_profitability_research as bid_ask_research
from profitability_research import evaluate_net_expectancy, _signal


def make_candles(count=1300):
    rows = []
    price = 2000.0
    for i in range(count):
        # Deterministic alternating drift creates valid OHLC data without
        # encoding a guaranteed winning strategy.
        drift = 0.22 if (i // 90) % 2 == 0 else -0.18
        open_price = price
        close = open_price + drift + (0.12 if i % 7 < 4 else -0.10)
        high = max(open_price, close) + 0.35
        low = min(open_price, close) - 0.35
        rows.append({
            "time": i * 900,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
        })
        price = close
    return rows


def test_requires_minimum_history():
    result = evaluate_net_expectancy(make_candles(999))
    assert result["status"] == "insufficient_data"


def test_returns_profitability_metrics_and_no_execution():
    result = evaluate_net_expectancy(make_candles())
    assert result["status"] == "complete"
    assert "expectancy_r" in result["holdout"]
    assert "profit_factor" in result["holdout"]
    assert "max_drawdown_r" in result["holdout"]
    assert result["execution_enabled"] is False
    assert set(result["directional_breakdown"]["holdout"]) == {"buy", "sell"}
    directional = result["directional_breakdown"]["holdout"]
    for side_metrics in directional.values():
        assert "expectancy_r" in side_metrics
        assert "profit_factor" in side_metrics
        assert "max_drawdown_r" in side_metrics
    assert sum(item["trades"] for item in directional.values()) == result["holdout"]["trades"]
    assert sum(item["net_r"] for item in directional.values()) == pytest.approx(result["holdout"]["net_r"], abs=0.0002)


def test_costs_cannot_improve_trade_returns():
    candles = make_candles()
    free = evaluate_net_expectancy(candles, spread_cost=0.0)
    costly = evaluate_net_expectancy(candles, spread_cost=0.5)
    if free["holdout"]["trades"] and costly["holdout"]["trades"]:
        assert costly["holdout"]["net_r"] <= free["holdout"]["net_r"]


def test_rejects_bad_costs_and_unsorted_data():
    with pytest.raises(ValueError):
        evaluate_net_expectancy(make_candles(), spread_cost=-0.1)
    candles = make_candles()
    candles[10], candles[11] = candles[11], candles[10]
    with pytest.raises(ValueError):
        evaluate_net_expectancy(candles)



def test_sell_candidate_requires_confirmed_bearish_regime():
    rows = []
    for i in range(61):
        close = 2200.0 - i
        open_price = close + 0.3
        rows.append({
            "time": i * 900,
            "open": open_price,
            "high": open_price + 0.1,
            "low": close - 0.1,
            "close": close,
        })
    # Strong bearish close below the prior 20-candle low.
    rows.append({
        "time": 61 * 900,
        "open": 2139.0,
        "high": 2139.2,
        "low": 2137.8,
        "close": 2138.0,
    })
    setup = _signal(rows, len(rows) - 1)
    assert setup is not None
    assert setup[0] == -1
    assert setup[1] > 0



def test_sell_candidate_rejects_non_bearish_breakout_candle():
    rows = []
    for i in range(61):
        close = 2200.0 - i
        open_price = close + 0.3
        rows.append({
            "time": i * 900,
            "open": open_price,
            "high": open_price + 0.1,
            "low": close - 0.1,
            "close": close,
        })
    rows.append({
        "time": 61 * 900,
        "open": 2137.5,
        "high": 2139.2,
        "low": 2137.2,
        "close": 2138.0,
    })
    assert _signal(rows, len(rows) - 1) is None


from bid_ask_profitability_research import evaluate_bid_ask_expectancy


def test_bid_ask_evaluator_uses_aligned_streams_and_reports_spread():
    bid = make_candles()
    ask = [{key: (value + 0.4 if key in ("open", "high", "low", "close") else value)
            for key, value in row.items()} for row in bid]
    result = evaluate_bid_ask_expectancy(bid, ask)
    assert result["status"] == "complete"
    assert result["execution_model"].startswith("BUY ask-entry/bid-exit")
    assert result["spread_at_open"]["mean"] == pytest.approx(0.4)
    assert result["execution_enabled"] is False


def test_bid_ask_evaluator_rejects_misaligned_timestamps():
    bid = make_candles()
    ask = [{key: (value + 0.4 if key in ("open", "high", "low", "close") else value)
            for key, value in row.items()} for row in bid]
    ask[100]["time"] += 1
    with pytest.raises(ValueError, match="identical timestamps"):
        evaluate_bid_ask_expectancy(bid, ask)


def test_bid_ask_evaluator_rejects_ask_below_bid():
    bid = make_candles()
    ask = [{key: (value + 0.4 if key in ("open", "high", "low", "close") else value)
            for key, value in row.items()} for row in bid]
    ask[100]["close"] = bid[100]["close"] - 0.1
    with pytest.raises(ValueError, match="must not be below"):
        evaluate_bid_ask_expectancy(bid, ask)



def test_simulators_never_exit_before_entry_at_development_boundary(monkeypatch):
    bid = make_candles()
    ask = [{key: (value + 0.4 if key in ("open", "high", "low", "close") else value)
            for key, value in row.items()} for row in bid]

    def signal_only_on_last_allowed_index(rows, index):
        return (1, 1.0) if index == 60 else None

    monkeypatch.setattr(base_research, "_signal", signal_only_on_last_allowed_index)
    base_trades = base_research._simulate(
        bid, 56, 61, 24, 1.5, 2.0, 0.0, 0.0
    )
    assert base_trades == []

    monkeypatch.setattr(bid_ask_research, "_signal", signal_only_on_last_allowed_index)
    bid_ask_trades = bid_ask_research._simulate(
        bid, ask, 56, 61, 24, 1.5, 2.0, 0.0, 0.0
    )
    assert bid_ask_trades == []
