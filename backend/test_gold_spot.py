import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class GoldSpotRetryTests(unittest.TestCase):
    @patch("main._fetch_json_with_retries")
    def test_gold_spot_uses_shared_retry_helper(self, fetch_json):
        fetch_json.return_value = {
            "spot_usd_oz": 4321.5,
            "updated_at": "2026-11-17T15:00:00Z",
            "data_state": {"status": "recent"},
        }

        result = main.gold_spot()

        self.assertEqual(result["symbol"], "XAUUSD")
        self.assertEqual(result["price"], 4321.5)
        args, kwargs = fetch_json.call_args
        self.assertEqual(kwargs["attempts"], 3)
        self.assertEqual(kwargs["timeout"], 15)
        self.assertIn("xaus.com/api/v1/spot", args[0].full_url)

    @patch("main._fetch_json_with_retries")
    def test_gold_spot_rejects_response_without_price(self, fetch_json):
        fetch_json.return_value = {"data_state": {"status": "recent"}}

        with self.assertRaises(HTTPException) as raised:
            main.gold_spot()

        self.assertEqual(raised.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
