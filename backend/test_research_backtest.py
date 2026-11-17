import unittest

from research_backtest import run_directional_backtest


def trend_candles(count=240, rising=True):
    rows = []
    price = 2000.0
    for index in range(count):
        change = (0.25 if rising else -0.25)
        price += change
        rows.append({
            "time": 1_700_000_000 + index * 60,
            "open": price - change / 2,
            "high": price + 0.1,
            "low": price - 0.1,
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
