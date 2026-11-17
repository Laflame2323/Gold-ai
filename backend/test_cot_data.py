import unittest
from cot_data import COTDataError, normalise_cot_rows


class COTNormalisationTests(unittest.TestCase):
    def test_managed_money_net_and_weekly_change(self):
        rows = [
            {"report_date_as_yyyy_mm_dd":"2026-11-03T00:00:00.000","open_interest_all":"1000","m_money_positions_long_all":"600","m_money_positions_short_all":"300","prod_merc_positions_long":"200","prod_merc_positions_short":"250","swap_positions_long_all":"120","swap__positions_short_all":"100"},
            {"report_date_as_yyyy_mm_dd":"2026-11-10T00:00:00.000","open_interest_all":"1100","m_money_positions_long_all":"650","m_money_positions_short_all":"300"},
        ]
        result = normalise_cot_rows(rows)
        self.assertEqual(result[-1]["managed_money_net"], 350)
        self.assertEqual(result[-1]["managed_money_net_change"], 50)
        self.assertEqual(result[-1]["expected_release_date"], "2026-11-13")
        self.assertEqual(result[-1]["producer_merchant_net"], -50)
        self.assertEqual(result[-1]["swap_dealer_net"], 20)

    def test_invalid_rows_are_not_fabricated(self):
        with self.assertRaises(COTDataError):
            normalise_cot_rows([{"report_date_as_yyyy_mm_dd":"bad"}])


if __name__ == "__main__":
    unittest.main()
