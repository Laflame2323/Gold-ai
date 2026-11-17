import unittest

from indicators.market_structure import analyse_market_structure


def candles_from_closes(closes):
    return [
        {
            "open": value - 0.1,
            "high": value + 0.5,
            "low": value - 0.5,
            "close": value,
            "volume": 1,
        }
        for value in closes
    ]


class MarketStructureTests(unittest.TestCase):
    def test_insufficient_history_is_unconfirmed(self):
        result = analyse_market_structure(candles_from_closes([10, 11, 10]), swing_window=1)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["trend"], "UNCONFIRMED")

    def test_higher_highs_and_higher_lows_are_detected(self):
        closes = [10, 11, 12, 11, 10, 11, 13, 12, 11, 12, 14, 13, 12]
        result = analyse_market_structure(candles_from_closes(closes), swing_window=1)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["trend"], "HIGHER_HIGHS_HIGHER_LOWS")
        self.assertEqual(result["breakout"], "NONE")

    def test_close_above_last_confirmed_swing_high_is_flagged(self):
        closes = [10, 11, 12, 11, 10, 11, 13, 12, 11, 12, 14, 13, 15]
        result = analyse_market_structure(candles_from_closes(closes), swing_window=1)
        self.assertEqual(result["breakout"], "BULLISH_BREAK_OF_STRUCTURE")

    def test_non_finite_prices_are_rejected(self):
        candles = candles_from_closes([10, 11, 12, 11, 10, 11, 13, 12, 11, 12])
        candles[3]["close"] = float("nan")
        result = analyse_market_structure(candles, swing_window=1)
        self.assertEqual(result["status"], "invalid_data")


if __name__ == "__main__":
    unittest.main()
