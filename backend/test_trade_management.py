import unittest
from trade_management import TIMEFRAME_PROFILES, manage_open_trade

class TradeProtectionTests(unittest.TestCase):
    def test_all_timeframes(self):
        self.assertEqual(set(TIMEFRAME_PROFILES), {"M1", "M5", "M15", "M30", "H1", "H4", "D1"})

    def test_buy_locks_profit(self):
        r = manage_open_trade(side="BUY", timeframe="H1", entry_price=100, current_price=104, best_price=104, current_stop=98, atr=2)
        self.assertTrue(r.profit_protection_active)
        self.assertGreater(r.proposed_stop, 100)

    def test_sell_locks_profit(self):
        r = manage_open_trade(side="SELL", timeframe="H1", entry_price=100, current_price=96, best_price=96, current_stop=102, atr=2)
        self.assertTrue(r.profit_protection_active)
        self.assertLess(r.proposed_stop, 100)

    def test_buy_stop_only_moves_up(self):
        r = manage_open_trade(side="BUY", timeframe="M5", entry_price=100, current_price=103, best_price=104, current_stop=101, atr=1)
        self.assertGreaterEqual(r.proposed_stop, 101)

    def test_sell_stop_only_moves_down(self):
        r = manage_open_trade(side="SELL", timeframe="M5", entry_price=100, current_price=97, best_price=96, current_stop=99, atr=1)
        self.assertLessEqual(r.proposed_stop, 99)

    def test_stop_hit_closes_both_sides(self):
        cases = [
            dict(side="BUY", current_price=98, current_stop=99),
            dict(side="SELL", current_price=102, current_stop=101),
        ]
        for c in cases:
            r = manage_open_trade(timeframe="M15", entry_price=100, best_price=100, atr=1, **c)
            self.assertTrue(r.should_close)
            self.assertEqual(r.close_reason, "trailing_stop_hit")

    def test_confirmed_reversal_closes(self):
        for side in ("BUY", "SELL"):
            stop = 95 if side == "BUY" else 105
            r = manage_open_trade(side=side, timeframe="H4", entry_price=100, current_price=100, best_price=100, current_stop=stop, atr=2, confirmed_reversal=True)
            self.assertEqual(r.close_reason, "confirmed_reversal")

    def test_unknown_timeframe_rejected(self):
        with self.assertRaises(ValueError):
            manage_open_trade(side="BUY", timeframe="W1", entry_price=100, current_price=101, best_price=101, current_stop=98, atr=1)

if __name__ == "__main__":
    unittest.main()
