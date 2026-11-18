import unittest

from research_backtest import (
    run_directional_backtest, compare_directional_horizons,
    chronological_holdout_backtest,
)


def trend_candles(count=240, rising=True):
    rows = []
    price = 2000.0
    for index in range(count):
        change = (0.25 if rising else -0.25)
        price += change
        rows.append({
            "time": 1_700_000_000 + index * 60,
            "open": price - change / 2,
            "high": max(price - change / 2, price) + 0.1,
            "low": min(price - change / 2, price) - 0.1,
            "close": price,
        })
    return rows


class DirectionalBacktestTests(unittest.TestCase):
    def test_short_history_is_not_scored(self):
        result = run_directional_backtest(trend_candles(70), horizon=5)
        self.assertEqual(result["status"], "insufficient_data")

    def test_backtest_reports_metrics_and_does_not_score_unfinished_horizon(self):
        result = run_directional_backtest(trend_candles(240), horizon=5)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["candle_count"], 240)
        self.assertEqual(result["evaluated_decision_points"], 176)
        self.assertIn("accuracy_pct", result)
        self.assertIn("coverage_pct", result)
        self.assertEqual(result["signals_tested"], result["buy"]["signals"] + result["sell"]["signals"])
        independent = result["non_overlapping_check"]
        self.assertLessEqual(independent["signals_tested"], result["signals_tested"])
        if result["signals_tested"]:
            self.assertGreater(independent["signals_tested"], 0)
        self.assertTrue(result["overlapping_outcome_windows"])

    def test_minimum_sample_requirement_counts_only_scoreable_decisions(self):
        too_short = run_directional_backtest(trend_candles(163), horizon=5)
        self.assertEqual(too_short["status"], "insufficient_data")
        self.assertEqual(too_short["required_candle_count"], 164)

        exact = run_directional_backtest(trend_candles(164), horizon=5)
        self.assertEqual(exact["status"], "complete")
        self.assertEqual(exact["evaluated_decision_points"], 100)

    def test_horizon_comparison_reports_all_requested_horizons(self):
        result = compare_directional_horizons(
            trend_candles(300), horizons=(1, 3, 5, 10, 20), minimum_samples=100
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            [row["horizon_candles"] for row in result["comparisons"]],
            [1, 3, 5, 10, 20],
        )
        self.assertTrue(all(row["evaluated_decision_points"] >= 100 for row in result["comparisons"]))
        self.assertFalse(result["execution_enabled"])

    def test_chronological_holdout_scores_only_later_decisions(self):
        candles = trend_candles(600)
        result = chronological_holdout_backtest(
            candles, horizon=5, minimum_samples=100, holdout_fraction=0.25
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["development_candles"], 450)
        self.assertEqual(result["holdout_candles"], 150)
        self.assertEqual(result["split_index"], 450)
        self.assertEqual(result["development_last_scored_decision_index"], 444)
        self.assertEqual(result["development_last_scored_exit_index"], 449)
        self.assertEqual(result["holdout_first_scored_decision_index"], 450)
        self.assertEqual(result["holdout_last_scored_decision_index"], 594)
        self.assertEqual(result["development"]["candle_count"], 450)
        self.assertEqual(result["untouched_holdout"]["evaluated_decision_points"], 145)
        self.assertEqual(result["untouched_holdout"]["required_candle_count"], 555)
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["costs_included"])

    def test_backtest_can_start_scoring_after_indicator_warmup(self):
        result = run_directional_backtest(
            trend_candles(300), horizon=5, minimum_samples=100, start_index=150
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["evaluated_decision_points"], 145)

    def test_holdout_fraction_is_bounded(self):
        for fraction in (0.0, 0.6, True):
            with self.subTest(fraction=fraction):
                with self.assertRaises(ValueError):
                    chronological_holdout_backtest(
                        trend_candles(300), holdout_fraction=fraction
                    )

    def test_horizon_comparison_rejects_duplicate_horizons(self):
        with self.assertRaises(ValueError):
            compare_directional_horizons(trend_candles(240), horizons=(1, 1))

    def test_minimum_samples_must_be_positive_integer(self):
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    run_directional_backtest(trend_candles(240), minimum_samples=invalid)

    def test_non_increasing_timestamps_are_rejected(self):
        candles = trend_candles(120)
        candles[10]["time"] = candles[9]["time"]
        with self.assertRaises(ValueError):
            run_directional_backtest(candles)

    def test_invalid_ohlc_is_rejected(self):
        candles = trend_candles(120)
        candles[20]["high"] = candles[20]["low"] - 1
        with self.assertRaises(ValueError):
            run_directional_backtest(candles)

    def test_horizon_must_be_bounded_integer(self):
        with self.assertRaises(ValueError):
            run_directional_backtest(trend_candles(120), horizon=0)
        with self.assertRaises(ValueError):
            run_directional_backtest(trend_candles(120), horizon=True)


if __name__ == "__main__":
    unittest.main()
