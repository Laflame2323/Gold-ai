import unittest

from vwap_strategy_lab import run_vwap_strategy_lab


def sample_candles(count=420):
    rows = []
    price = 2000.0
    for i in range(count):
        # Deterministic, non-flat synthetic OHLC; not intended as market evidence.
        drift = 0.035 if (i // 45) % 2 == 0 else -0.025
        price += drift + ((i % 7) - 3) * 0.012
        rows.append({
            "time": 1_700_000_000 + i * 900,
            "open": price - 0.04,
            "high": price + 0.12,
            "low": price - 0.13,
            "close": price,
            "volume": 100 + (i % 13),
        })
    return rows


class VwapStrategyLabTests(unittest.TestCase):
    def test_returns_research_only_result(self):
        result = run_vwap_strategy_lab(sample_candles(), minimum_samples=20)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(result["volume_kind"], "unknown")

    def test_missing_volume_refuses_to_calculate_vwap(self):
        candles = sample_candles()
        candles[210]["volume"] = None
        result = run_vwap_strategy_lab(candles, minimum_samples=20)
        self.assertEqual(result["status"], "volume_unavailable")

    def test_insufficient_history_is_reported(self):
        result = run_vwap_strategy_lab(sample_candles(100), minimum_samples=20)
        self.assertEqual(result["status"], "insufficient_data")

    def test_rejects_unordered_candles(self):
        candles = sample_candles()
        candles[5], candles[6] = candles[6], candles[5]
        with self.assertRaises(ValueError):
            run_vwap_strategy_lab(candles, minimum_samples=20)

    def test_rejects_negative_volume(self):
        candles = sample_candles()
        candles[210]["volume"] = -1
        with self.assertRaises(ValueError):
            run_vwap_strategy_lab(candles, minimum_samples=20)


if __name__ == "__main__":
    unittest.main()
