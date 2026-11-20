import csv
import tempfile
import unittest
from pathlib import Path

from getdata_research_evaluation import load_m1


class DukascopyBidAskLoadingTests(unittest.TestCase):
    def test_timestamp_milliseconds_and_bid_ask_spread_are_aligned(self):
        with tempfile.TemporaryDirectory() as directory:
            bid_path = Path(directory) / "bid.csv"
            ask_path = Path(directory) / "ask.csv"
            fields = ["timestamp", "open", "high", "low", "close", "volume"]
            bid_rows = [
                [1700000000000, 2000.0, 2001.0, 1999.0, 2000.5, 10],
                [1700000060000, 2000.5, 2001.5, 2000.0, 2001.0, 12],
            ]
            ask_rows = [
                [1700000000000, 2000.2, 2001.2, 1999.2, 2000.7, 10],
                [1700000060000, 2000.7, 2001.7, 2000.2, 2001.2, 12],
            ]
            for path, rows in ((bid_path, bid_rows), (ask_path, ask_rows)):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(fields)
                    writer.writerows(rows)

            candles, audit = load_m1(bid_path, ask_path)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0]["time"], 1700000000)
        self.assertAlmostEqual(candles[0]["spread"], 0.2, places=6)
        self.assertEqual(audit["matched_bid_ask_minutes"], 2)
        self.assertEqual(audit["unmatched_bid_minutes"], 0)
        self.assertAlmostEqual(audit["mean_spread_price"], 0.2, places=6)


if __name__ == "__main__":
    unittest.main()
