import unittest

from research_ml import evaluate_logistic_research


def synthetic_candles(count=1400):
    rows = []
    price = 2300.0
    for i in range(count):
        # Deterministic, alternating movement avoids a one-class fixture.
        change = (0.18 if (i // 9) % 2 == 0 else -0.13) + ((i % 5) - 2) * 0.012
        open_price = price
        price += change
        rows.append({
            "time": 1_700_000_000 + i * 60,
            "open": open_price,
            "high": max(open_price, price) + 0.08,
            "low": min(open_price, price) - 0.08,
            "close": price,
        })
    return rows


class LogisticResearchTests(unittest.TestCase):
    def test_small_history_does_not_train(self):
        result = evaluate_logistic_research(synthetic_candles(500), horizon=5)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["ai_trained"])

    def test_chronological_candidate_reports_separate_test_block(self):
        result = evaluate_logistic_research(synthetic_candles(), horizon=5)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["candidate_model_trained"])
        self.assertFalse(result["ai_trained"])
        self.assertFalse(result["production_model_persisted"])
        self.assertGreaterEqual(result["split_samples"]["train"], 50)
        self.assertGreaterEqual(result["split_samples"]["validation"], 50)
        self.assertGreaterEqual(result["split_samples"]["test"], 50)
        self.assertEqual(result["scaler_fit_on"], "training block only")
        self.assertEqual(result["purge_candles_each_boundary"], 5)
        self.assertIn("balanced_accuracy_pct", result["untouched_test"])
        self.assertIn("confusion_matrix", result["untouched_test"])
        self.assertFalse(result["execution_enabled"])

    def test_rejects_non_increasing_time(self):
        candles = synthetic_candles()
        candles[100]["time"] = candles[99]["time"]
        with self.assertRaises(ValueError):
            evaluate_logistic_research(candles)

    def test_rejects_invalid_horizon(self):
        for value in (0, 101, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    evaluate_logistic_research(synthetic_candles(), horizon=value)


if __name__ == "__main__":
    unittest.main()
