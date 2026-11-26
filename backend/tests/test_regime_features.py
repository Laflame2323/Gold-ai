import pytest

from regime_features import build_regime_features


def candles(count=180):
    rows = []
    price = 2000.0
    for index in range(count):
        price += 0.35 if index % 7 else -0.10
        rows.append({
            "time": 1_700_000_000 + index * 3600,
            "open": price - 0.2,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
        })
    return rows


def test_builds_causal_features_after_warmup():
    result = build_regime_features(candles())
    assert result["row_count"] > 0
    assert result["warmup_count"] > 0
    first = next(row for row in result["rows"] if row is not None)
    assert first["atr"] > 0
    assert 0 <= first["efficiency_ratio"] <= 1
    assert first["trend_regime"] in {"directional", "choppy", "mixed"}
    assert first["volatility_regime"] in {"low", "normal", "high"}


def test_future_changes_do_not_change_earlier_features():
    original = candles()
    baseline = build_regime_features(original)
    changed = [dict(row) for row in original]
    changed[-1]["high"] += 100
    changed[-1]["low"] -= 100
    updated = build_regime_features(changed)
    for index in (60, 80, 120, 150):
        assert baseline["rows"][index] == updated["rows"][index]


def test_invalid_ohlc_is_rejected():
    rows = candles()
    rows[10]["high"] = 1000
    with pytest.raises(ValueError, match="invalid high"):
        build_regime_features(rows)


def test_parameters_are_validated():
    with pytest.raises(ValueError, match="integer"):
        build_regime_features(candles(), atr_period=14.5)
    with pytest.raises(ValueError, match="smaller"):
        build_regime_features(candles(), trend_period=50, slow_period=50)
