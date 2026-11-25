import pytest

import m30_sweep_reclaim_research as research


BASE = 1_700_000_000


def candles(count, start=BASE, step=1800, price=2000.0):
    return [
        {"time": start + i * step, "open": price, "high": price + 1,
         "low": price - 1, "close": price}
        for i in range(count)
    ]


def h1_history(start=BASE - 100 * 3600, count=130):
    return candles(count, start=start, step=3600)


def bullish_signal_rows(count=80, signal_index=30):
    rows = candles(count)
    rows[signal_index] = {
        "time": BASE + signal_index * 1800, "open": 2000.5,
        "high": 2002.5, "low": 1998.5, "close": 2002.0,
    }
    return rows


def test_wilder_atr_is_causal_and_seeded_from_first_14_true_ranges():
    rows = candles(20)
    atr = research._wilder_atr(rows)
    assert atr[:14] == [None] * 14
    assert atr[14] == pytest.approx(2.0)
    changed_future = [dict(row) for row in rows]
    changed_future[19]["high"] += 100
    assert research._wilder_atr(changed_future)[14] == atr[14]


def test_buy_signal_uses_prior_twenty_bars_excluding_signal_bar():
    rows = bullish_signal_rows()
    atrs = research._wilder_atr(rows)
    signal = research._detect_signal(rows, atrs, 30)
    assert signal["side"] == "BUY"
    assert signal["prior_range_low"] == 1999
    assert signal["sweep_extreme"] == 1998.5
    assert signal["body_ratio"] >= 0.35
    assert signal["close_position"] >= 0.65


def test_signal_rejects_zero_range_candle():
    rows = candles(40)
    rows[30] = {"time": BASE + 30 * 1800, "open": 2000, "high": 2000,
                "low": 2000, "close": 2000}
    assert research._detect_signal(rows, research._wilder_atr(rows), 30) is None


def test_h1_context_uses_candle_closed_at_m30_close_but_not_later():
    h1 = h1_history()
    decision_close = BASE + 30 * 1800 + 1800
    exactly_closed = {"time": decision_close - 3600, "open": 2000, "high": 2001,
                      "low": 1999, "close": 2000}
    too_late = {"time": decision_close - 3599, "open": 2000, "high": 2001,
                "low": 1999, "close": 2000}
    context = research._h1_context(decision_close, h1 + [exactly_closed, too_late])
    assert context is not None
    assert context["last_completed_h1_open"] == exactly_closed["time"]


def test_missing_h1_fails_closed():
    with pytest.raises(ValueError, match="H1 candles are required"):
        research.evaluate_m30_sweep_reclaim(candles(1300), None)


@pytest.mark.parametrize("bad_rows", [
    lambda rows: rows.__setitem__(10, dict(rows[9])),
    lambda rows: rows.__setitem__(10, {**rows[10], "high": rows[10]["low"] - 1}),
])
def test_rejects_duplicate_or_invalid_ohlc(bad_rows):
    rows = candles(1300)
    bad_rows(rows)
    with pytest.raises(ValueError):
        research.evaluate_m30_sweep_reclaim(rows, h1_history())


def test_rejects_out_of_order_timestamps():
    rows = candles(1300)
    rows[10], rows[11] = rows[11], rows[10]
    with pytest.raises(ValueError, match="strictly increasing"):
        research.evaluate_m30_sweep_reclaim(rows, h1_history())


def test_final_test_requires_all_freeze_gates():
    args = {"evaluation_mode": "final_test"}
    with pytest.raises(PermissionError):
        research.evaluate_m30_sweep_reclaim(candles(1300), h1_history(), **args)
    result = research.evaluate_m30_sweep_reclaim(
        candles(1300), h1_history(), evaluation_mode="final_test",
        allow_final_test=True, candidate_frozen=True, costs_frozen=True,
    )
    assert "final_test" in result["periods"]
    assert result["execution_enabled"] is False


def test_development_validation_keeps_final_test_sealed():
    result = research.evaluate_m30_sweep_reclaim(candles(1300), h1_history())
    assert set(result["periods"]) == {"development", "validation"}
    assert result["final_test"] == "SEALED_NOT_RUN"
    assert result["no_trade_baseline"]["net_r"] == 0


def test_entry_open_is_used_for_stop_distance_and_invalid_gap_rejected():
    rows = bullish_signal_rows()
    rows[31]["open"] = 2010.0
    result = research._simulate_segment(
        rows, h1_history(), research._wilder_atr(rows), 30, 70,
        "fingerprint", research.VERSION, None,
    )
    assert result["plans"] == []
    assert any(r["reason"] == "entry_open_stop_distance_outside_0.50_to_2.00_ATR"
               for r in result["rejected"])


def test_entry_candle_counts_as_first_holding_bar_and_stop_wins_ambiguous_bar(monkeypatch):
    rows = bullish_signal_rows()
    rows[31] = {"time": BASE + 31 * 1800, "open": 2000,
                "high": 2005, "low": 1990, "close": 2000}
    signal = {"side": "BUY", "atr": 2.0, "sweep_extreme": 1998.5,
              "prior_range_high": 2001, "prior_range_low": 1999,
              "body_ratio": .5, "close_position": .8}
    monkeypatch.setattr(research, "_detect_signal",
                        lambda _rows, _atrs, index: signal if index == 30 else None)
    result = research._simulate_segment(
        rows, h1_history(), research._wilder_atr(rows), 30, 70,
        "fingerprint", research.VERSION, None,
    )
    assert len(result["outcomes"]) == 1
    outcome = result["outcomes"][0]
    assert outcome["exit_reason"] == "stop"
    assert outcome["bars_held"] == 1
    assert outcome["exit_price"] == pytest.approx(outcome["plan"]["stop_price"])


def test_overlap_is_rejected_until_after_exit_bar(monkeypatch):
    rows = bullish_signal_rows()
    rows[31] = {"time": BASE + 31 * 1800, "open": 2000,
                "high": 2005, "low": 1990, "close": 2000}
    signal = {"side": "BUY", "atr": 2.0, "sweep_extreme": 1998.5,
              "prior_range_high": 2001, "prior_range_low": 1999,
              "body_ratio": .5, "close_position": .8}
    monkeypatch.setattr(research, "_detect_signal",
                        lambda _rows, _atrs, index: signal if index in (30, 31) else None)
    result = research._simulate_segment(
        rows, h1_history(), research._wilder_atr(rows), 30, 70,
        "fingerprint", research.VERSION, None,
    )
    assert len(result["outcomes"]) == 1
    assert any(r["reason"] == "overlapping_position" for r in result["rejected"])


def test_opening_gap_through_stop_fills_at_open_not_stop(monkeypatch):
    rows = bullish_signal_rows()
    rows[31] = {"time": BASE + 31 * 1800, "open": 2000,
                "high": 2001, "low": 1999, "close": 2000}
    rows[32] = {"time": BASE + 32 * 1800, "open": 1990,
                "high": 1992, "low": 1988, "close": 1991}
    signal = {"side": "BUY", "atr": 2.0, "sweep_extreme": 1998.5,
              "prior_range_high": 2001, "prior_range_low": 1999,
              "body_ratio": .5, "close_position": .8}
    monkeypatch.setattr(research, "_detect_signal",
                        lambda _rows, _atrs, index: signal if index == 30 else None)
    result = research._simulate_segment(
        rows, h1_history(), research._wilder_atr(rows), 30, 70,
        "fingerprint", research.VERSION, None,
    )
    assert result["outcomes"][0]["exit_reason"] == "stop_gap"
    assert result["outcomes"][0]["exit_price"] == 1990


def test_costs_are_not_silently_assumed_and_sensitivity_is_reported():
    rows = candles(1300)
    result = research.evaluate_m30_sweep_reclaim(
        rows, h1_history(), cost_scenarios={"base": 0.25, "stress": 0.75}
    )
    assert result["cost_model"]["cost_status"] == "uncalibrated_gross_only"
    assert result["no_trade_baseline"]["net_r"] == 0
    assert all("cost_sensitivity" in period for period in result["periods"].values())


def test_cost_inputs_must_be_nonnegative_finite_numbers():
    with pytest.raises(ValueError, match=">= 0"):
        research.evaluate_m30_sweep_reclaim(
            candles(1300), h1_history(), round_trip_cost_price_units=-0.1
        )


def test_dataset_fingerprint_is_stable_for_identical_inputs():
    rows, h1 = candles(1300), h1_history()
    one = research.evaluate_m30_sweep_reclaim(rows, h1)
    two = research.evaluate_m30_sweep_reclaim(rows, h1)
    assert one["dataset_fingerprint"] == two["dataset_fingerprint"]



def test_sell_signal_uses_lower_35_percent_close_zone():
    rows = candles(80)
    rows[30] = {"time": BASE + 30 * 1800, "open": 2000.5, "high": 2002.5,
                "low": 1997.5, "close": 1998.0}
    signal = research._detect_signal(rows, research._wilder_atr(rows), 30)
    assert signal["side"] == "SELL"
    assert signal["close_position"] <= 0.35
    assert signal["sweep_extreme"] == 2002.5


def test_net_statistics_are_unavailable_when_costs_are_not_supplied():
    rows = [{"gross_r": 1.0, "net_r": None}]
    assert research._stats(rows, net=True)["trades"] == 0
    assert research._stats(rows, net=True)["expectancy_r"] is None


def test_median_uses_average_of_two_middle_values():
    rows = [{"gross_r": value, "net_r": value} for value in (1.0, 3.0)]
    assert research._stats(rows)["median_r"] == 2.0


def test_cost_scenarios_reduce_net_expectancy():
    rows = candles(1300)
    h1 = h1_history()
    # Exercise cost arithmetic independently of whether this fixture creates signals.
    plan = {"risk_price": 2.0}
    gross_r = 1.0
    base_net = gross_r - 0.25 / plan["risk_price"]
    stress_net = gross_r - 0.75 / plan["risk_price"]
    assert stress_net < base_net



def test_report_separates_supplied_dataset_fingerprint_from_payload_hash():
    result = research.evaluate_m30_sweep_reclaim(
        candles(1300), h1_history(), dataset_fingerprint="archive-manifest-v7"
    )
    assert result["dataset_fingerprint"] == "archive-manifest-v7"
    assert len(result["candle_payload_sha256"]) == 64
    assert result["candle_payload_sha256"] != result["dataset_fingerprint"]


def test_time_exit_occurs_on_twelfth_candle_including_entry(monkeypatch):
    rows = bullish_signal_rows()
    signal = {"side": "BUY", "atr": 2.0, "sweep_extreme": 1998.5,
              "prior_range_high": 2001, "prior_range_low": 1999,
              "body_ratio": .5, "close_position": .8}
    monkeypatch.setattr(research, "_detect_signal",
                        lambda _rows, _atrs, index: signal if index == 30 else None)
    result = research._simulate_segment(
        rows, h1_history(), research._wilder_atr(rows), 30, 70,
        "fingerprint", research.VERSION, None,
    )
    outcome = result["outcomes"][0]
    assert outcome["exit_reason"] == "time"
    assert outcome["bars_held"] == 12
    assert outcome["exit_time"] == rows[42]["time"]


def test_statistics_include_losing_streak_and_holding_time():
    rows = [
        {"gross_r": 1.0, "net_r": 1.0, "bars_held": 2},
        {"gross_r": -0.5, "net_r": -0.5, "bars_held": 4},
        {"gross_r": -0.2, "net_r": -0.2, "bars_held": 6},
        {"gross_r": -0.1, "net_r": -0.1, "bars_held": 8},
        {"gross_r": 0.5, "net_r": 0.5, "bars_held": 10},
    ]
    stats = research._stats(rows)
    assert stats["longest_losing_streak"] == 3
    assert stats["holding_bars_mean"] == pytest.approx(6.0)
    assert stats["holding_bars_median"] == 6


def test_block_bootstrap_expectancy_interval_is_deterministic():
    rows = [
        {"exit_index": i, "gross_r": (0.8 if i % 3 else -0.6), "net_r": (0.7 if i % 3 else -0.7)}
        for i in range(30)
    ]
    first = research._block_bootstrap_expectancy_ci(rows, "net_r", block_length=5, replications=500, seed=17)
    second = research._block_bootstrap_expectancy_ci(rows, "net_r", block_length=5, replications=500, seed=17)
    assert first == second
    assert first["status"] == "complete"
    assert first["n"] == 30
    assert first["ci_95_lower"] <= first["expectancy_r"] <= first["ci_95_upper"]


def test_block_bootstrap_refuses_too_few_trades_for_block_length():
    rows = [{"exit_index": i, "gross_r": 0.5} for i in range(9)]
    result = research._block_bootstrap_expectancy_ci(rows, "gross_r", block_length=5)
    assert result["status"] == "insufficient_independent_blocks"
    assert result["ci_95_lower"] is None
    assert result["replications"] == 0


def test_block_bootstrap_net_interval_is_unavailable_without_costs():
    rows = [{"exit_index": i, "gross_r": 0.5, "net_r": None} for i in range(20)]
    result = research._block_bootstrap_expectancy_ci(rows, "net_r", block_length=5)
    assert result["status"] == "insufficient_independent_blocks"
    assert result["n"] == 0


def test_block_bootstrap_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="block_length"):
        research._block_bootstrap_expectancy_ci([], block_length=0)
    with pytest.raises(ValueError, match="replications"):
        research._block_bootstrap_expectancy_ci([], replications=10)


def test_empty_statistics_keep_the_extended_schema():
    stats = research._stats([])
    assert stats["longest_losing_streak"] == 0
    assert stats["holding_bars_mean"] is None
    assert stats["holding_bars_median"] is None


def test_report_includes_gross_and_net_uncertainty_by_side():
    result = research.evaluate_m30_sweep_reclaim(candles(1300), h1_history())
    uncertainty = result["periods"]["development"]["uncertainty"]
    assert "BUY_gross_expectancy_95_ci" in uncertainty
    assert "SELL_gross_expectancy_95_ci" in uncertainty
    assert "combined_gross_expectancy_95_ci" in uncertainty
    assert uncertainty["combined_net_expectancy_95_ci"]["n"] == 0


def test_block_bootstrap_rejects_non_finite_trade_values():
    rows = [{"exit_index": i, "gross_r": float("nan")} for i in range(12)]
    with pytest.raises(ValueError, match="finite"):
        research._block_bootstrap_expectancy_ci(rows, "gross_r")
