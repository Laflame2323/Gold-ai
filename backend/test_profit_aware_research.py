import unittest
import math

from profit_aware_research import (
    _select_threshold,
    _trade_metrics_r,
    _trade_returns_r,
    _best_side_rows,
    _calendar_features,
    _regime_features,
    _simulate_directional_barrier,
)


class ProfitAwareResearchTests(unittest.TestCase):
    def test_trade_returns_use_barrier_risk_and_cost(self):
        outcomes = [1, -1, 0]
        sides = [1, 1, -1]
        values = _trade_returns_r(
            outcomes, sides, [0, 1, 2], pt_atr=1.5, sl_atr=1.0,
            cost_atr=0.1,
        )
        self.assertEqual(values, [1.4, -1.1, -0.1])

    def test_bid_ask_long_entry_and_exit_are_used(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 101.5, "low": 100.5, "close": 101.0,
             "ask_open": 101.0, "ask_high": 101.5, "ask_low": 100.5, "ask_close": 101.0},
            {"open": 101.0, "high": 102.2, "low": 100.5, "close": 102.0,
             "ask_open": 102.0, "ask_high": 103.0, "ask_low": 101.5, "ask_close": 102.5},
        ]
        result = _simulate_directional_barrier(
            candles, 0, 2, 1.0, 1.0, 1.0, 1
        )
        self.assertEqual(result, (1, 2, 1.0, False))

    def test_bid_ask_short_uses_ask_side_for_exit_barriers(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
             "ask_open": 100.2, "ask_high": 100.5, "ask_low": 99.5, "ask_close": 100.2},
            {"open": 99.5, "high": 100.0, "low": 98.5, "close": 99.0,
             "ask_open": 99.7, "ask_high": 100.5, "ask_low": 98.5, "ask_close": 99.2},
        ]
        result = _simulate_directional_barrier(
            candles, 0, 2, 1.0, 1.0, 1.0, -1
        )
        self.assertEqual(result, (-1, 2, 1.0, False))

    def test_ambiguous_barrier_touch_assumes_stop_first(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 101.5, "low": 100.5, "close": 101.0,
             "ask_open": 101.0, "ask_high": 101.5, "ask_low": 100.5, "ask_close": 101.0},
            {"open": 101.0, "high": 102.5, "low": 99.5, "close": 101.0,
             "ask_open": 102.0, "ask_high": 103.0, "ask_low": 100.0, "ask_close": 101.0},
        ]
        result = _simulate_directional_barrier(
            candles, 0, 2, 1.0, 1.0, 1.0, 1
        )
        self.assertEqual(result, (-1, 2, -1.0, True))

    def test_vertical_expiry_marks_to_market(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 101.5, "low": 100.5, "close": 101.0,
             "ask_open": 101.0, "ask_high": 101.5, "ask_low": 100.5, "ask_close": 101.0},
            {"open": 101.0, "high": 101.8, "low": 100.5, "close": 101.5,
             "ask_open": 102.0, "ask_high": 102.2, "ask_low": 101.5, "ask_close": 102.0},
        ]
        result = _simulate_directional_barrier(
            candles, 0, 2, 1.0, 1.0, 1.0, 1
        )
        self.assertEqual(result, (0, 2, 0.5, False))

    def test_realized_gross_returns_are_used_for_net_r(self):
        values = _trade_returns_r(
            [0, 0], [1, -1], [0, 1], 1.0, 1.0, 0.1,
            gross_returns_r=[0.5, -1.0],
        )
        self.assertEqual(values, [0.4, -1.1])

    def test_metrics_report_expectancy_and_drawdown(self):
        result = _trade_metrics_r([1.5, -1.0, 0.0, 1.5, -1.0])
        self.assertEqual(result["trades"], 5)
        self.assertEqual(result["total_net_r"], 1.0)
        self.assertEqual(result["mean_net_r"], 0.2)
        self.assertEqual(result["max_drawdown_r"], 1.0)

    def test_empty_metrics_include_conservative_bound(self):
        result = _trade_metrics_r([])
        self.assertIsNone(result["mean_net_r_lower_90_bound"])

    def test_threshold_is_selected_on_positive_validation_expectancy(self):
        outcomes = [1] * 30 + [-1] * 70
        sides = [1] * 100
        probabilities = [0.90] * 30 + [0.60] * 70
        rows = list(range(100))
        threshold, table, positive = _select_threshold(
            probabilities, outcomes, sides, rows,
            pt_atr=1.5, sl_atr=1.0, cost_atr=0.1,
        )
        self.assertEqual(threshold, 0.65)
        self.assertTrue(positive)
        selected = next(item for item in table if item["threshold"] == threshold)
        self.assertEqual(selected["trades"], 30)
        self.assertGreater(selected["mean_net_r"], 0)

    def test_uncertain_positive_mean_is_rejected_by_lower_bound(self):
        outcomes = [1] * 12 + [-1] * 8
        sides = [1] * 20
        probabilities = [0.80] * 20
        threshold, _table, positive = _select_threshold(
            probabilities, outcomes, sides, list(range(20)),
            pt_atr=1.5, sl_atr=1.0, cost_atr=0.1,
        )
        self.assertEqual(threshold, 1.01)
        self.assertFalse(positive)

    def test_regime_features_use_valid_completed_candles(self):
        candles = []
        for i in range(60):
            close = 2000.0 + i * 0.2
            candles.append({
                "time": i * 1800, "open": close - 0.1,
                "high": close + 0.4, "low": close - 0.4,
                "close": close, "volume": 100 + i,
            })
        atr_values = [0.8] * 60
        result = _regime_features(candles, 40, atr_values)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(math.isfinite(value) for value in result))
        self.assertGreater(result[0], 0)
        self.assertGreaterEqual(result[3], 0)
        self.assertLessEqual(result[3], 1)

    def test_calendar_features_are_finite_and_cyclical(self):
        first = _calendar_features(1_700_000_000)
        same_hour_next_day = _calendar_features(1_700_086_400)
        self.assertEqual(len(first), 4)
        self.assertTrue(all(-1.0 <= value <= 1.0 for value in first))
        self.assertAlmostEqual(first[0], same_hour_next_day[0], places=6)
        self.assertAlmostEqual(first[1], same_hour_next_day[1], places=6)
        self.assertNotAlmostEqual(first[2], same_hour_next_day[2], places=6)

    def test_only_highest_probability_direction_is_kept_per_candle(self):
        rows = [0, 1, 2, 3]
        decisions = [10, 10, 11, 11]
        selected = _best_side_rows([0.70, 0.85, 0.90, 0.60], rows, decisions)
        self.assertEqual(set(selected), {10, 11})
        self.assertEqual(selected[10][1], 1)
        self.assertEqual(selected[11][1], 2)

    def test_directional_threshold_counts_one_trade_per_candle(self):
        outcomes, sides, probabilities, decisions = [], [], [], []
        for decision in range(25):
            outcomes.extend([1, -1])
            sides.extend([1, -1])
            probabilities.extend([0.85, 0.60])
            decisions.extend([decision, decision])
        rows = list(range(50))
        threshold, table, positive = _select_threshold(
            probabilities, outcomes, sides, rows,
            pt_atr=1.5, sl_atr=1.0, cost_atr=0.1,
            decisions=decisions,
        )
        self.assertEqual(threshold, 0.50)
        self.assertTrue(positive)
        chosen = next(item for item in table if item["threshold"] == threshold)
        self.assertEqual(chosen["trades"], 25)
        self.assertEqual(chosen["coverage_pct"], 100.0)

    def test_no_positive_validation_edge_means_no_trades(self):
        outcomes = [1] * 20 + [-1] * 80
        sides = [1] * 100
        probabilities = [0.51] * 20 + [0.90] * 80
        threshold, _table, positive = _select_threshold(
            probabilities, outcomes, sides, list(range(100)),
            pt_atr=1.5, sl_atr=1.0, cost_atr=0.0,
        )
        self.assertEqual(threshold, 1.01)
        self.assertFalse(positive)


if __name__ == "__main__":
    unittest.main()
