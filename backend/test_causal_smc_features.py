import math
import unittest

from causal_smc_features import FEATURE_NAMES, causal_smc_features


def make_candles(count=100, mode="trend"):
    rows = []
    price = 2300.0
    for index in range(count):
        if mode == "flat":
            change = 0.0
        elif mode == "trend":
            change = 0.35 if index % 7 != 0 else -0.04
        else:
            change = 0.18 if index % 2 == 0 else -0.16
        next_price = price + change
        rows.append({
            "time": 1_700_000_000 + index * 1800,
            "open": price,
            "high": max(price, next_price) + 0.08,
            "low": min(price, next_price) - 0.08,
            "close": next_price,
            "volume": 100 + index % 11,
        })
        price = next_price
    return rows


class CausalSmcFeatureTests(unittest.TestCase):
    def test_feature_vector_matches_names_and_is_finite(self):
        candles = make_candles()
        values = causal_smc_features(candles, 70, atr=0.5)
        self.assertEqual(len(values), len(FEATURE_NAMES))
        self.assertTrue(all(math.isfinite(value) for value in values))

    def test_cusum_detects_persistent_upward_change(self):
        values = causal_smc_features(make_candles(mode="trend"), 90, atr=0.5)
        up_index = FEATURE_NAMES.index("regime_cusum_up_strength")
        down_index = FEATURE_NAMES.index("regime_cusum_down_strength")
        trigger_index = FEATURE_NAMES.index("regime_cusum_up_trigger")
        self.assertGreater(values[up_index], values[down_index])
        self.assertEqual(values[trigger_index], 1.0)

    def test_flat_prices_do_not_create_cusum_signal(self):
        values = causal_smc_features(make_candles(mode="flat"), 90, atr=0.5)
        up_index = FEATURE_NAMES.index("regime_cusum_up_strength")
        down_index = FEATURE_NAMES.index("regime_cusum_down_strength")
        self.assertEqual(values[up_index], 0.0)
        self.assertEqual(values[down_index], 0.0)

    def test_future_candles_cannot_change_past_features(self):
        candles = make_candles()
        before = causal_smc_features(candles, 70, atr=0.5)
        changed = [dict(row) for row in candles]
        for index in range(71, len(changed)):
            changed[index]["open"] *= 1.4
            changed[index]["high"] *= 1.4
            changed[index]["low"] *= 1.4
            changed[index]["close"] *= 1.4
        after = causal_smc_features(changed, 70, atr=0.5)
        self.assertEqual(before, after)

    def test_rejects_invalid_index_or_atr(self):
        candles = make_candles()
        with self.assertRaises(ValueError):
            causal_smc_features(candles, 29, atr=0.5)
        with self.assertRaises(ValueError):
            causal_smc_features(candles, 70, atr=0.0)


if __name__ == "__main__":
    unittest.main()
