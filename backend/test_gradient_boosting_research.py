import unittest

from gradient_boosting_research import evaluate_gradient_boosting
from triple_barrier_research import evaluate_triple_barrier_meta


def candles(count, interval, start=1_700_000_000):
    rows = []
    price = 2300.0
    for index in range(count):
        change = (0.15 if (index // 8) % 2 == 0 else -0.11) + ((index % 5) - 2) * 0.01
        next_price = price + change
        rows.append({"time": start + index * interval, "open": price,
                     "high": max(price, next_price) + 0.1,
                     "low": min(price, next_price) - 0.1, "close": next_price})
        price = next_price
    return rows


def history():
    return {"H4": candles(500, 14400), "H1": candles(1800, 3600),
            "M30": candles(3600, 1800), "M15": candles(7200, 900)}


class GradientBoostingResearchTests(unittest.TestCase):
    def test_gradient_boosting_uses_chronological_validation_and_test(self):
        result = evaluate_gradient_boosting(history(), horizon=5)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["model_type"],
                         "validation_selected_hist_gradient_boosting_research_candidate")
        self.assertGreaterEqual(result["split_samples"]["train"], 50)
        self.assertGreaterEqual(result["split_samples"]["validation"], 50)
        self.assertGreaterEqual(result["split_samples"]["test"], 50)
        self.assertEqual(len(result["validation_candidates"]), 6)
        self.assertIn("balanced_accuracy_pct", result["untouched_test"])
        self.assertEqual(result["confidence_coverage"]["total_test_samples"],
                         result["untouched_test"]["samples"])
        self.assertTrue(result["research_only"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["ai_trained"])

    def test_requires_all_timeframes(self):
        data = history()
        del data["M15"]
        with self.assertRaises(ValueError):
            evaluate_gradient_boosting(data)


    def test_atr_triple_barrier_meta_label_evaluator(self):
        result = evaluate_triple_barrier_meta(history(), horizon=12)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["model_type"],
                         "atr_triple_barrier_m30_rule_side_meta_label_hist_gradient_boosting")
        self.assertGreaterEqual(result["split_samples"]["train"], 50)
        self.assertGreaterEqual(result["split_samples"]["validation"], 50)
        self.assertGreaterEqual(result["split_samples"]["test"], 50)
        self.assertEqual(len(result["validation_candidates"]), 6)
        self.assertEqual(result["base_timeframe"], "M30")\n        self.assertIn("primary_test_meta_label_win_rate_pct", result)
        self.assertEqual(len(result["confidence_coverage"]), 6)
        self.assertTrue(result["research_only"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["ai_trained"])

    def test_triple_barrier_supports_h1_comparison(self):\n        result = evaluate_triple_barrier_meta(history(), horizon=12, base_timeframe="H1")\n        self.assertEqual(result["status"], "complete")\n        self.assertEqual(result["base_timeframe"], "H1")\n\n    def test_triple_barrier_rejects_invalid_horizon(self):
        with self.assertRaises(ValueError):
            evaluate_triple_barrier_meta(history(), horizon=1)


if __name__ == "__main__":
    unittest.main()
