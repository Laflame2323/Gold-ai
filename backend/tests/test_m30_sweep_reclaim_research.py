import pytest

from m30_sweep_reclaim_research import (
    _cost,
    _h1_context,
    _signal,
    evaluate_m30_sweep_reclaim,
)


def flat_candles(count, start=0, step=1800, price=2000.0):
    return [
        {"time": start + i * step, "open": price, "high": price + 1,
         "low": price - 1, "close": price}
        for i in range(count)
    ]


def test_signal_uses_only_prior_twenty_candles_and_next_open():
    rows = flat_candles(22)
    rows[20] = {"time": 20 * 1800, "open": 2000.5, "high": 2002.5,
                "low": 1998.8, "close": 2002.4}
    rows[21] = {"time": 21 * 1800, "open": 2002.4, "high": 2003,
                "low": 2001.8, "close": 2002.6}
    signal = _signal(rows, 20)
    assert signal is not None
    assert signal["side"] == 1
    assert signal["entry"] == rows[21]["open"]


def test_h1_context_excludes_unfinished_h1_bar():
    h1 = flat_candles(60, start=0, step=3600)
    decision_time = h1[55]["time"] + 3600
    context_before = _h1_context(decision_time, h1[:56])
    future = {"time": decision_time, "open": 9999, "high": 10000,
              "low": 9998, "close": 9999}
    context_with_future = _h1_context(decision_time, h1[:56] + [future])
    assert context_before == context_with_future


def test_final_test_is_sealed_by_default():
    m30 = flat_candles(1300)
    h1 = flat_candles(700, step=3600)
    result = evaluate_m30_sweep_reclaim(m30, h1)
    assert result["status"] == "complete"
    assert result["candidate_version"] == "m30-sweep-reclaim-v1"
    assert result["final_test"] == "SEALED_NOT_RUN"
    assert result["execution_enabled"] is False


def test_final_test_requires_explicit_opening():
    m30 = flat_candles(1300)
    h1 = flat_candles(700, step=3600)
    result = evaluate_m30_sweep_reclaim(m30, h1, run_final_test=True)
    assert isinstance(result["final_test"], dict)
    assert result["final_test"]["period"] == "final_test"


def test_reports_variant_count_and_multiple_testing_warning():
    m30 = flat_candles(1300)
    h1 = flat_candles(700, step=3600)
    result = evaluate_m30_sweep_reclaim(m30, h1, variant_count=4)
    assert result["multiple_testing"]["strategy_variants_tested"] == 4
    assert "elevated" in result["multiple_testing"]["warning"]


def test_rejects_invalid_session_costs():
    with pytest.raises(ValueError, match="Invalid non-negative cost"):
        _cost("London", {"London": {"spread": -0.2}})


def test_rejects_unsorted_m30_timestamps():
    m30 = flat_candles(1300)
    h1 = flat_candles(700, step=3600)
    m30[10], m30[11] = m30[11], m30[10]
    with pytest.raises(ValueError, match="strictly increasing"):
        evaluate_m30_sweep_reclaim(m30, h1)
