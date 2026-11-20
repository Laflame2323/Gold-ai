import unittest

from profit_aware_research import (
    _select_threshold,
    _trade_metrics_r,
    _trade_returns_r,
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

    def test_metrics_report_expectancy_and_drawdown(self):
        result = _trade_metrics_r([1.5, -1.0, 0.0, 1.5, -1.0])
        self.assertEqual(result["trades"], 5)
        self.assertEqual(result["total_net_r"], 1.0)
        self.assertEqual(result["mean_net_r"], 0.2)
        self.assertEqual(result["max_drawdown_r"], 1.0)

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
