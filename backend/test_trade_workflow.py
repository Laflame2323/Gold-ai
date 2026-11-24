import unittest

from trade_workflow import build_trade_plan, evaluate_risk_gate


NOW = 1_800_000_000


def candidate(**overrides):
    data = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "timeframe": "M15",
        "strategy_id": "test-breakout",
        "strategy_version": "1.0.0",
        "data_source": "MT5:DemoBroker",
        "broker_feed_verified": True,
        "instrument_enabled": True,
        "candle_closed": True,
        "trigger_confirmed": True,
        "candle_close_time": NOW - 60,
        "decision_time": NOW - 55,
        "expiry_time": NOW + 1800,
        "entry_price": 2650.0,
        "stop_price": 2645.0,
        "target_price": 2660.0,
        "risk_pct": 0.5,
        "round_trip_cost_price": 0.5,
    }
    data.update(overrides)
    return data


def limits(**overrides):
    data = {
        "max_risk_pct_per_trade": 1.0,
        "max_daily_risk_pct": 2.0,
        "min_net_reward_risk": 1.0,
        "max_trades_per_day": 3,
    }
    data.update(overrides)
    return data


class TradeWorkflowTests(unittest.TestCase):
    def test_builds_reproducible_buy_plan_from_closed_candle(self):
        first = build_trade_plan(candidate(), now=NOW)
        second = build_trade_plan(candidate(), now=NOW)
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(first["status"], "RESEARCH_CANDIDATE")
        self.assertTrue(first["research_only"])
        self.assertFalse(first["execution_enabled"])
        self.assertEqual(first["gross_reward_risk"], 2.0)
        self.assertEqual(first["net_reward_risk"], 1.727273)

    def test_supports_sell_plan_with_correct_price_order(self):
        plan = build_trade_plan(candidate(
            side="SELL",
            entry_price=2650.0,
            stop_price=2655.0,
            target_price=2640.0,
        ), now=NOW)
        self.assertEqual(plan["side"], "SELL")
        self.assertEqual(plan["gross_reward_risk"], 2.0)

    def test_rejects_unclosed_candle(self):
        with self.assertRaisesRegex(ValueError, "fully closed"):
            build_trade_plan(candidate(candle_closed=False), now=NOW)

    def test_rejects_unconfirmed_trigger(self):
        with self.assertRaisesRegex(ValueError, "not been confirmed"):
            build_trade_plan(candidate(trigger_confirmed=False), now=NOW)

    def test_rejects_stale_candle(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            build_trade_plan(candidate(candle_close_time=NOW - 7200, decision_time=NOW - 7190), now=NOW)

    def test_rejects_future_decision(self):
        with self.assertRaisesRegex(ValueError, "Future-dated"):
            build_trade_plan(candidate(decision_time=NOW + 1), now=NOW)

    def test_rejects_invalid_buy_stop_target_order(self):
        with self.assertRaisesRegex(ValueError, "stop < entry < target"):
            build_trade_plan(candidate(stop_price=2651.0), now=NOW)

    def test_eurusd_stays_disabled_until_enabled(self):
        with self.assertRaisesRegex(ValueError, "EURUSD is disabled"):
            build_trade_plan(candidate(symbol="EURUSD"), now=NOW)

    def test_risk_gate_blocks_reference_feed(self):
        plan = build_trade_plan(candidate(broker_feed_verified=False), now=NOW)
        result = evaluate_risk_gate(plan, limits(), now=NOW)
        self.assertEqual(result["status"], "BLOCK")
        self.assertTrue(any("Verified broker candles" in reason for reason in result["reasons"]))

    def test_risk_gate_blocks_daily_risk_and_trade_count(self):
        plan = build_trade_plan(candidate(), now=NOW)
        result = evaluate_risk_gate(
            plan,
            limits(max_daily_risk_pct=0.75, max_trades_per_day=1),
            {"risk_used_pct": 0.5, "trades_taken": 1},
            now=NOW,
        )
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(len(result["reasons"]), 2)

    def test_risk_gate_pass_is_still_research_only(self):
        plan = build_trade_plan(candidate(), now=NOW)
        result = evaluate_risk_gate(plan, limits(), now=NOW)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["research_only"])
        self.assertFalse(result["order_submitted"])

    def test_risk_gate_blocks_costs_that_erase_the_reward(self):
        plan = build_trade_plan(candidate(round_trip_cost_price=11.0), now=NOW)
        result = evaluate_risk_gate(plan, limits(), now=NOW)
        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("Net reward:risk is below the configured minimum.", result["reasons"])

    def test_risk_gate_blocks_expired_plan(self):
        plan = build_trade_plan(candidate(expiry_time=NOW + 1), now=NOW)
        result = evaluate_risk_gate(plan, limits(), now=NOW + 2)
        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("The trade plan has expired.", result["reasons"])


if __name__ == "__main__":
    unittest.main()
