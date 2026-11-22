# Dukascopy XAUUSD historical-data pilot

This is a research-only acquisition path. It writes local CSV and JSON provenance files. It does not write to Supabase, change the MT5 archive, or touch production.

## Source and format

The downloader retrieves Dukascopy XAUUSD one-minute candle files separately for BID and ASK from the public datafeed. The .bi5 files are LZMA-alone compressed 24-byte records (big-endian seconds from UTC midnight, integer open/close/low/high prices, and volume). XAUUSD integer prices are divided by 1,000.

The output preserves BID and ASK OHLCV separately and calculates open/close spread only. It does not fabricate a mid-price series. Rows are joined on exact UTC minute timestamps; missing days, incomplete one-sided days, and unmatched minutes are reported. A SHA-256 and source/date metadata are written beside the CSV.

Dukascopy is a reference feed, not Exness. Its prices, spread, tick volume, sessions, and candle construction can differ from the broker feed. Do not silently combine the feeds. Compare overlapping timestamps against MT5 first.

## Run a small pilot

From the repository backend directory, run:

    python dukascopy_data.py --start 2026-11-17 --end 2026-11-19 --output-dir ../data/dukascopy

The end date is exclusive. This pilot covers November 17 and 18 UTC. Weekends or periods without files may be reported as missing.

## Quality gates before database import

1. Confirm non-empty output and SHA-256.
2. Check duplicates, OHLC bounds, positive prices, and non-negative volumes.
3. Inspect missing days, one-sided days, and unmatched BID/ASK minutes.
4. Confirm ASK open/close is not below BID.
5. Compare overlapping M1 timestamps against Exness MT5; the feeds are not interchangeable.
6. Only after review, create a separate research dataset table with provenance. Never write this feed into the broker-specific production archive.

Downloading data does not establish model accuracy.
