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
        self.assertIn("precision", result["untouched_test"])
        self.assertIn("recall", result["untouched_test"])
        self.assertIn("up", result["untouched_test"]["precision"])
        self.assertIn("down", result["untouched_test"]["precision"])
        self.assertIn("prediction_counts", result["untouched_test"])
        coverage = result["confidence_coverage"]
        self.assertEqual(coverage["total_test_samples"], result["untouched_test"]["samples"])
        self.assertEqual([x["probability_threshold"] for x in coverage["thresholds"]],
                         [0.55, 0.60, 0.65, 0.70])
        self.assertTrue(all(0 <= x["coverage_pct"] <= 100
                            and 0 <= x["abstention_pct"] <= 100
                            for x in coverage["thresholds"]))
        self.assertTrue(all(x["selected_samples"] <= coverage["total_test_samples"]
                            for x in coverage["thresholds"]))
        self.assertIsNotNone(coverage["brier_score"])
        self.assertGreaterEqual(coverage["brier_score"], 0)
        self.assertLessEqual(coverage["brier_score"], 1)
        self.assertIsNotNone(coverage["expected_calibration_error"])
        self.assertGreaterEqual(coverage["expected_calibration_error"], 0)
        self.assertLessEqual(coverage["expected_calibration_error"], 1)
        self.assertIsNotNone(coverage["max_calibration_error"])
        self.assertGreaterEqual(coverage["max_calibration_error"], 0)
        self.assertLessEqual(coverage["max_calibration_error"], 1)
        self.assertEqual(len(coverage["calibration_bins"]), 5)
        self.assertTrue(all(0 <= x["samples"] <= coverage["total_test_samples"]
                            for x in coverage["calibration_bins"]))

        self.assertFalse(result["execution_enabled"])

    def test_walk_forward_uses_sequential_purged_folds(self):
        result = evaluate_logistic_research(synthetic_candles(), horizon=5)
        walk = result["walk_forward"]
        self.assertEqual(walk["total_folds"], 4)
        self.assertGreaterEqual(walk["completed_folds"], 3)
        completed = [fold for fold in walk["folds"] if fold["status"] == "complete"]
        self.assertTrue(all(fold["test_samples"] >= 50 for fold in completed))
        self.assertTrue(all(fold["scaler_fit_on"] == "this fold's training block only"
                            for fold in completed))
        self.assertIsNotNone(walk["mean_fold_balanced_accuracy_pct"])

    def test_rejects_non_finite_prices(self):
        candles = synthetic_candles()
        candles[100]["close"] = float("nan")
        with self.assertRaises(ValueError):
            evaluate_logistic_research(candles)

    def test_rejects_inconsistent_ohlc(self):
        candles = synthetic_candles()
        candles[100]["high"] = candles[100]["low"] - 1
        with self.assertRaises(ValueError):
            evaluate_logistic_research(candles)

    def test_single_direction_training_block_does_not_train(self):
        candles = []
        price = 2000.0
        for i in range(1400):
            next_price = price + 0.2
            candles.append({
                "time": 1_700_000_000 + i * 60,
                "open": price,
                "high": next_price + 0.05,
                "low": price - 0.05,
                "close": next_price,
            })
            price = next_price
        result = evaluate_logistic_research(candles, horizon=5)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["ai_trained"])

    def test_rejects_non_increasing_time(self):
        candles = synthetic_candles()
        candles[100]["time"] = candles[99]["time"]
        with self.assertRaises(ValueError):
            evaluate_logistic_research(candles)

    def test_neutral_zone_filter_is_reported_and_reduces_samples(self):
        candles = synthetic_candles()
        unfiltered = evaluate_logistic_research(candles, horizon=5)
        filtered = evaluate_logistic_research(candles, horizon=5, min_move_pct=0.01)
        self.assertEqual(filtered["neutral_zone_min_move_pct"], 0.01)
        self.assertGreaterEqual(filtered["excluded_small_move_outcomes"], 0)
        self.assertLessEqual(filtered["eligible_samples"], unfiltered["eligible_samples"])

    def test_rejects_invalid_neutral_zone(self):
        for value in (-0.1, 10.1, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    evaluate_logistic_research(synthetic_candles(), min_move_pct=value)

    def test_rejects_invalid_horizon(self):
        for value in (0, 101, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    evaluate_logistic_research(synthetic_candles(), horizon=value)


if __name__ == "__main__":
    unittest.main()
