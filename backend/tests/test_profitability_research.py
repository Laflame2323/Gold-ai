import math
import pytest

from profitability_research import evaluate_net_expectancy


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
