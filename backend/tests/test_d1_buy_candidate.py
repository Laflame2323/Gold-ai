import pytest

from d1_buy_candidate import evaluate_d1_buy_candidate


def candles(count=1300):
    rows = []
    price = 2000.0
    for i in range(count):
        drift = 0.22 if (i // 90) % 2 == 0 else -0.18
        opening = price
        closing = opening + drift + (0.12 if i % 7 < 4 else -0.10)
        rows.append({
            "time": i * 86400,
            "open": opening,
            "high": max(opening, closing) + 0.35,
            "low": min(opening, closing) - 0.35,
            "close": closing,
        })
        price = closing
    return rows


def ask_from(bid, spread=0.4):
    return [{
        key: value + spread if key in ("open", "high", "low", "close") else value
        for key, value in row.items()
    } for row in bid]


def test_d1_candidate_requires_minimum_history():
    bid = candles(999)
    result = evaluate_d1_buy_candidate(bid, ask_from(bid))
    assert result["status"] == "insufficient_data"


def test_d1_candidate_reports_research_only_metrics():
    bid = candles()
    result = evaluate_d1_buy_candidate(bid, ask_from(bid))
    assert result["status"] == "complete"
    assert result["execution_enabled"] is False
    assert result["ai_trained"] is False
    assert result["parameters"]["stop_atr"] == 2.0
    assert result["parameters"]["target_r"] == 0.25
    assert "win_rate_pct" in result["holdout"]
    assert "expectancy_r" in result["holdout"]
    assert "profit_factor" in result["holdout"]
    assert result["research_gate"] in {
        "candidate_passes_initial_gate", "not_proven_profitable"
    }


def test_d1_candidate_rejects_misaligned_ask_stream():
    bid = candles()
    ask = ask_from(bid)
    ask[10]["time"] += 1
    with pytest.raises(ValueError, match="identical timestamps"):
        evaluate_d1_buy_candidate(bid, ask)


def test_d1_candidate_rejects_negative_costs():
    bid = candles()
    with pytest.raises(ValueError, match="non-negative"):
        evaluate_d1_buy_candidate(bid, ask_from(bid), commission_cost=-0.01)
