from datetime import date, datetime, timezone
import lzma, struct, unittest
from dukascopy_data import decode_candle_file, merge_bid_ask

class DukascopyDataTests(unittest.TestCase):
    def payload(self, records):
        raw = b"".join(struct.pack(">IIIIIf", *row) for row in records)
        return lzma.compress(raw, format=lzma.FORMAT_ALONE)

    def test_decode_utc_timestamp_and_price_scale(self):
        result = decode_candle_file(self.payload([(0, 2000000, 2001000, 1999000, 2002000, 12.0)]),
                                    date(2026, 1, 1))
        stamp = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
        self.assertEqual(result[stamp]["open"], 2000.0)
        self.assertEqual(result[stamp]["high"], 2002.0)

    def test_reject_partial_record(self):
        with self.assertRaises(ValueError):
            decode_candle_file(lzma.compress(b"bad", format=lzma.FORMAT_ALONE), date(2026, 1, 1))

    def test_reject_invalid_ohlc(self):
        with self.assertRaises(ValueError):
            decode_candle_file(self.payload([(0, 2000000, 2001000, 2000500, 2002000, 1.0)]),
                               date(2026, 1, 1))

    def test_bid_ask_join_and_unmatched_counts(self):
        b = {"open": 2000.0, "high": 2002.0, "low": 1999.0, "close": 2001.0, "volume": 10.0}
        a = {"open": 2000.2, "high": 2002.2, "low": 1999.2, "close": 2001.2, "volume": 9.0}
        rows, bid_only, ask_only = merge_bid_ask({60:b, 120:b}, {60:a, 180:a})
        self.assertEqual(rows[0]["spread_close"], 0.2)
        self.assertEqual((bid_only, ask_only), (1, 1))

    def test_reject_crossed_quote(self):
        b = {"open": 2000.0, "high": 2002.0, "low": 1999.0, "close": 2001.0, "volume": 1.0}
        a = {"open": 1999.9, "high": 2002.2, "low": 1999.2, "close": 2001.2, "volume": 1.0}
        with self.assertRaises(ValueError):
            merge_bid_ask({60:b}, {60:a})

if __name__ == "__main__":
    unittest.main()
