import unittest
from macro_data import MacroDataError, parse_fred_csv


class FredParsingTests(unittest.TestCase):
    def test_parses_values_and_skips_missing_observations(self):
        csv_text = "observation_date,DGS10\n2026-11-13,4.12\n2026-11-14,.\n2026-11-17,4.08\n"
        rows = parse_fred_csv(csv_text, "DGS10")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["value"], 4.08)

    def test_rejects_unsupported_series(self):
        with self.assertRaises(MacroDataError):
            parse_fred_csv("observation_date,UNKNOWN\n2026-11-17,1\n", "UNKNOWN")

    def test_rejects_malformed_header(self):
        with self.assertRaises(MacroDataError):
            parse_fred_csv("date,DGS10\n2026-11-17,4.1\n", "DGS10")


if __name__ == "__main__":
    unittest.main()
