import unittest

from trade_replay import simulate_trade_plan, split_bid_ask_rows


def paired_rows():
    return [
        {
            "timestamp": 1000,
            "bid_open": 99.8, "bid_high": 101.0, "bid_low": 99.0, "bid_close": 100.0,
            "ask_open": 100.0, "ask_high": 101.2, "ask_low": 99.2, "ask_close": 100.2,
        },
        {
            "timestamp": 1060,
            "bid_open": 100.0, "bid_high": 111.0, "bid_low": 99.5, "bid_close": 110.0,
            "ask_open": 100.2, "ask_high": 111.2, "ask_low": 99.7, "ask_close": 110.2,
        },
        {
            "timestamp": 1120,
            "bid_open": 110.0, "bid_high": 111.0, "bid_low": 109.0, "bid_close": 110.0,
            "ask_open": 110.2, "ask_high": 111.2, "ask_low": 109.2, "ask_close": 110.2,
        },
    ]


def plan(**overrides):
    data = {
        "plan_id": "plan-test",
        "symbol": "XAUUSD",
        "side": "BUY",
        "decision_time": 1000,
        "expiry_time": 1180,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_price": 110.0,
    }
    data.update(overrides)
    return data


class TradeReplayTests(unittest.TestCase):
    def test_buy_enters_on_ask_and_exits_on_bid_target(self):
        bid, ask = split_bid_ask_rows(paired_rows())
        result = simulate_trade_plan(plan(), bid, ask, extra_cost_price=0.2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["side"], "BUY")
        self.assertEqual(result["actual_entry"], 100.0)
        self.assertEqual(result["actual_exit"], 110.0)
        self.assertEqual(result["exit_reason"], "target")
        self.assertAlmostEqual(result["net_r"], 1.96, places=5)

    def test_sell_enters_on_bid_and_exits_on_ask_target(self):
        rows = paired_rows()
        rows[1].update({
            "bid_open": 100.0, "bid_high": 100.5, "bid_low": 89.0, "bid_close": 90.0,
            "ask_open": 100.2, "ask_high": 100.7, "ask_low": 89.2, "ask_close": 90.2,
        })
        bid, ask = split_bid_ask_rows(rows)
        result = simulate_trade_plan(
            plan(side="SELL", entry_price=100.0, stop_price=105.0, target_price=90.0),
            bid, ask,
        )
        self.assertEqual(result["side"], "SELL")
        self.assertEqual(result["actual_entry"], 99.8)
        self.assertEqual(result["actual_exit"], 90.0)
        self.assertEqual(result["exit_reason"], "target")

    def test_stop_wins_when_same_bar_touches_stop_and_target(self):
        rows = paired_rows()
        rows[1].update({
            "bid_open": 100.0, "bid_high": 111.0, "bid_low": 94.0, "bid_close": 100.0,
            "ask_open": 100.2, "ask_high": 111.2, "ask_low": 94.2, "ask_close": 100.2,
        })
        bid, ask = split_bid_ask_rows(rows)
        result = simulate_trade_plan(plan(), bid, ask)
        self.assertEqual(result["exit_reason"], "stop")
        self.assertEqual(result["actual_exit"], 95.0)
        self.assertLess(result["gross_r"], 0)

    def test_gap_through_stop_uses_worse_opening_fill(self):
        rows = paired_rows()
        rows[1].update({
            "bid_open": 93.0, "bid_high": 94.0, "bid_low": 92.0, "bid_close": 93.0,
            "ask_open": 93.2, "ask_high": 94.2, "ask_low": 92.2, "ask_close": 93.2,
        })
        bid, ask = split_bid_ask_rows(rows)
        result = simulate_trade_plan(plan(decision_time=940), bid, ask)
        self.assertEqual(result["exit_reason"], "stop_gap")
        self.assertEqual(result["actual_exit"], 93.0)
        self.assertLess(result["gross_r"], -1.0)

    def test_rejects_mismatched_bid_ask_timestamps(self):
        bid, ask = split_bid_ask_rows(paired_rows())
        ask[1]["time"] += 1
        with self.assertRaisesRegex(ValueError, "identical timestamps"):
            simulate_trade_plan(plan(), bid, ask)

    def test_invalidated_entry_is_not_chased(self):
        rows = paired_rows()
        rows[0].update({
            "bid_open": 110.0, "bid_high": 111.0, "bid_low": 109.0, "bid_close": 110.0,
            "ask_open": 110.2, "ask_high": 111.2, "ask_low": 109.2, "ask_close": 110.2,
        })
        bid, ask = split_bid_ask_rows(rows)
        result = simulate_trade_plan(plan(decision_time=940), bid, ask)
        self.assertEqual(result["status"], "no_entry")
        self.assertIn("do not chase", result["reason"])

    def test_returns_no_entry_when_plan_expired_before_next_bar(self):
        bid, ask = split_bid_ask_rows(paired_rows())
        result = simulate_trade_plan(plan(expiry_time=1050), bid, ask)
        self.assertEqual(result["status"], "no_entry")

    def test_extra_cost_reduces_net_r_without_double_charging_spread(self):
        bid, ask = split_bid_ask_rows(paired_rows())
        free = simulate_trade_plan(plan(), bid, ask)
        charged = simulate_trade_plan(plan(), bid, ask, extra_cost_price=0.5)
        self.assertGreater(free["net_r"], charged["net_r"])
        self.assertEqual(charged["entry_spread"], 0.2)

    def test_time_exit_uses_last_complete_candle_before_expiry(self):
        rows = paired_rows()
        rows[1].update({
            "bid_open": 100.0, "bid_high": 102.0, "bid_low": 99.5, "bid_close": 101.0,
            "ask_open": 100.2, "ask_high": 102.2, "ask_low": 99.7, "ask_close": 101.2,
        })
        rows[2].update({
            "bid_open": 101.0, "bid_high": 102.0, "bid_low": 100.5, "bid_close": 101.5,
            "ask_open": 101.2, "ask_high": 102.2, "ask_low": 100.7, "ask_close": 101.7,
        })
        bid, ask = split_bid_ask_rows(rows)
        result = simulate_trade_plan(plan(), bid, ask)
        self.assertEqual(result["exit_reason"], "time_expiry")
        self.assertEqual(result["actual_exit"], 101.5)


if __name__ == "__main__":
    unittest.main()
