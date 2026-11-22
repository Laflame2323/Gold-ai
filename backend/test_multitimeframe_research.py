import unittest

from multitimeframe_research import evaluate_multitimeframe_research


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


class MultiTimeframeResearchTests(unittest.TestCase):
    def test_returns_chronological_research_metrics(self):
        result = evaluate_multitimeframe_research(history(), horizon=5)
        self.assertEqual(result["status"], "complete")
        self.assertIn(result["feature_count"], {9, 18, 27, 36})
        self.assertGreaterEqual(result["split_samples"]["train"], 50)
        self.assertGreaterEqual(result["split_samples"]["validation"], 50)
        self.assertGreaterEqual(result["split_samples"]["test"], 50)
        self.assertIn("balanced_accuracy_pct", result["untouched_test"])
        ablation = result["validation_ablation"]
        self.assertEqual(len(ablation["candidates"]), 8)
        self.assertIn(ablation["selected_class_weighting"], {"none", "inverse_frequency"})
        self.assertIn(ablation["best_validation_candidate"], {item["candidate"] for item in ablation["candidates"]})
        self.assertIn("validation-only", ablation["warning"])
        self.assertEqual(result["fit_diagnostics"]["selected_class_weighting"], ablation["selected_class_weighting"])
        self.assertFalse(result["ai_trained"])
        self.assertFalse(result["execution_enabled"])

    def test_no_labelled_samples_returns_insufficient_data(self):
        result = evaluate_multitimeframe_research(history(), min_move_pct=10.0)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["eligible_samples"], 0)
        self.assertFalse(result["ai_trained"])

    def test_insufficient_h1_history_is_reported(self):
        data = history()
        data["H1"] = data["H1"][:500]
        result = evaluate_multitimeframe_research(data)
        self.assertEqual(result["status"], "insufficient_data")

    def test_missing_timeframe_is_rejected(self):
        data = history()
        del data["M30"]
        with self.assertRaises(ValueError):
            evaluate_multitimeframe_research(data)


if __name__ == "__main__":
    unittest.main()
