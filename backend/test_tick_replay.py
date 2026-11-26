import unittest

from tick_replay import simulate_trade_plan_on_ticks


def plan(**overrides):
    value = {
        "plan_id": "tick-plan-1",
        "symbol": "XAUUSD",
        "side": "BUY",
        "decision_time": 100,
        "expiry_time": 110,
        "entry_price": 100.0,
        "stop_price": 98.0,
        "target_price": 104.0,
    }
    value.update(overrides)
    return value


def ticks():
    return [
        {"time_msc": 100000, "bid": 99.8, "ask": 100.0, "id": 1},
        {"time_msc": 101000, "bid": 100.2, "ask": 100.4, "id": 2},
        {"time_msc": 102000, "bid": 104.0, "ask": 104.2, "id": 3},
    ]


class TickReplayTests(unittest.TestCase):
    def test_buy_enters_ask_and_exits_bid_at_target(self):
        result = simulate_trade_plan_on_ticks(plan(), ticks())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["actual_entry"], 100.0)
        self.assertEqual(result["actual_exit"], 104.0)
        self.assertEqual(result["exit_reason"], "target")
        self.assertEqual(result["gross_r"], 2.0)

    def test_sell_enters_bid_and_exits_ask_at_target(self):
        rows = [
            {"time_msc": 100000, "bid": 100.0, "ask": 100.2, "id": 1},
            {"time_msc": 101000, "bid": 96.0, "ask": 96.2, "id": 2},
        ]
        result = simulate_trade_plan_on_ticks(
            plan(side="SELL", entry_price=100, stop_price=102, target_price=96.2), rows
        )
        self.assertEqual(result["actual_entry"], 100.0)
        self.assertEqual(result["actual_exit"], 96.2)
        self.assertEqual(result["exit_reason"], "target")

    def test_stop_is_triggered_on_first_quote_touch(self):
        rows = [
            {"time_msc": 100000, "bid": 99.8, "ask": 100.0, "id": 1},
            {"time_msc": 101000, "bid": 97.9, "ask": 98.1, "id": 2},
            {"time_msc": 102000, "bid": 104.0, "ask": 104.2, "id": 3},
        ]
        result = simulate_trade_plan_on_ticks(plan(), rows)
        self.assertEqual(result["exit_reason"], "stop")
        self.assertEqual(result["actual_exit"], 97.9)

    def test_rejects_invalidated_entry_without_chasing(self):
        rows = [{"time_msc": 100000, "bid": 104.0, "ask": 104.2, "id": 1}]
        result = simulate_trade_plan_on_ticks(plan(), rows)
        self.assertEqual(result["status"], "no_entry")
        self.assertIn("do not chase", result["reason"])

    def test_rejects_ask_below_bid(self):
        rows = [{"time_msc": 100000, "bid": 100.2, "ask": 100.0, "id": 1}]
        with self.assertRaisesRegex(ValueError, "ask cannot be below bid"):
            simulate_trade_plan_on_ticks(plan(), rows)

    def test_expired_plan_has_no_entry(self):
        result = simulate_trade_plan_on_ticks(plan(decision_time=90, expiry_time=99), ticks())
        self.assertEqual(result["status"], "no_entry")

    def test_commission_slippage_reduces_net_r(self):
        free = simulate_trade_plan_on_ticks(plan(), ticks())
        charged = simulate_trade_plan_on_ticks(plan(), ticks(), extra_cost_price=0.2)
        self.assertGreater(free["net_r"], charged["net_r"])

    def test_tick_order_is_validated(self):
        rows = list(reversed(ticks()))
        with self.assertRaisesRegex(ValueError, "ordered"):
            simulate_trade_plan_on_ticks(plan(), rows)


if __name__ == "__main__":
    unittest.main()
