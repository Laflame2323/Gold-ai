"""Research-only Dukascopy XAUUSD M1 BID/ASK downloader."""
from __future__ import annotations
import argparse, csv, hashlib, json, lzma, struct, time
import urllib.error, urllib.request
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
PRICE_SCALE = 1000.0
RECORD = struct.Struct(">IIIIIf")
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def decode_candle_file(payload: bytes, day: date) -> dict[int, dict]:
    if not payload:
        return {}
    raw = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    if len(raw) % RECORD.size:
        raise ValueError("Decoded Dukascopy file has a partial candle record.")
    midnight = datetime.combine(day, datetime_time.min, tzinfo=timezone.utc)
    result = {}
    for seconds, open_i, close_i, low_i, high_i, volume in RECORD.iter_unpack(raw):
        if seconds >= 86400:
            raise ValueError("Candle timestamp is outside its UTC day.")
        op, cl, lo, hi = (open_i / PRICE_SCALE, close_i / PRICE_SCALE,
                          low_i / PRICE_SCALE, high_i / PRICE_SCALE)
        if min(op, cl, lo, hi) <= 0 or lo > min(op, cl) or max(op, cl) > hi:
            raise ValueError("Dukascopy candle contains invalid OHLC prices.")
        if volume < 0:
            raise ValueError("Dukascopy candle contains negative volume.")
        # Dukascopy may fill closed minutes with a flat, zero-volume candle.
        # These are not traded observations and should not enter model features.
        if volume == 0 and op == cl == lo == hi:
            continue
        stamp = int((midnight + timedelta(seconds=seconds)).timestamp())
        if stamp in result:
            raise ValueError("Dukascopy file contains duplicate timestamps.")
        result[stamp] = {"open": op, "high": hi, "low": lo, "close": cl,
                         "volume": float(volume)}
    return result


def fetch_side(day: date, side: str, timeout: int = 45, attempts: int = 8):
    if side not in {"BID", "ASK"}:
        raise ValueError("Price side must be BID or ASK.")
    url = (f"{BASE_URL}/XAUUSD/{day.year}/{day.month - 1:02d}/"
           f"{day.day:02d}/{side}_candles_min_1.bi5")
    request = urllib.request.Request(url, headers={
        "User-Agent": "GoldAI-ResearchData/1.0",
        "Accept": "application/octet-stream",
    })
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return decode_candle_file(response.read(), day)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code not in RETRYABLE_HTTP or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == attempts - 1:
                raise
        time.sleep(min(2 ** attempt, 60))
    raise RuntimeError("Dukascopy download exhausted retries.")


def merge_bid_ask(bid: dict[int, dict], ask: dict[int, dict]):
    rows = []
    bid_times, ask_times = set(bid), set(ask)
    for stamp in sorted(bid_times & ask_times):
        b, a = bid[stamp], ask[stamp]
        if a["open"] < b["open"] or a["close"] < b["close"]:
            raise ValueError("ASK open/close is below BID at a matched minute.")
        row = {"timestamp": stamp}
        for side, values in (("bid", b), ("ask", a)):
            for field in ("open", "high", "low", "close", "volume"):
                row[f"{side}_{field}"] = values[field]
        row["spread_open"] = a["open"] - b["open"]
        row["spread_close"] = a["close"] - b["close"]
        rows.append(row)
    return rows, len(bid_times - ask_times), len(ask_times - bid_times)


def download_range(start: date, end: date, output_dir: Path):
    if end <= start:
        raise ValueError("End date must be later than start date (exclusive).")
    if (end - start).days > 31:
        raise ValueError("Pilot downloader is limited to 31 days per run.")
    rows, missing, incomplete = [], [], []
    unmatched_bid = unmatched_ask = 0
    for offset in range((end - start).days):
        day = start + timedelta(days=offset)
        bid = fetch_side(day, "BID")
        ask = fetch_side(day, "ASK")
        if not bid and not ask:
            missing.append(day.isoformat())
            continue
        if bid is None or ask is None:
            incomplete.append(day.isoformat())
            continue
        day_rows, bid_only, ask_only = merge_bid_ask(bid, ask)
        rows.extend(day_rows)
        unmatched_bid += bid_only
        unmatched_ask += ask_only
    rows.sort(key=lambda item: item["timestamp"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"xauusd_dukascopy_m1_bid_ask_{start:%Y%m%d}_{end:%Y%m%d}"
    csv_path = output_dir / f"{stem}.csv"
    fields = ["timestamp"] + [f"{side}_{field}" for side in ("bid", "ask")
             for field in ("open", "high", "low", "close", "volume")]
    fields += ["spread_open", "spread_close"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "dataset": "XAUUSD-DUKASCOPY-M1-BID-ASK", "provider": "Dukascopy",
        "instrument": "XAUUSD", "timeframe": "M1", "timezone": "UTC",
        "timestamp_unit": "unix_epoch_seconds", "price_scale": PRICE_SCALE,
        "date_range_start_inclusive": start.isoformat(),
        "date_range_end_exclusive": end.isoformat(), "rows": len(rows),
        "missing_both_sides_days": missing, "incomplete_one_side_days": incomplete,
        "unmatched_bid_minutes": unmatched_bid, "unmatched_ask_minutes": unmatched_ask,
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "csv_file": csv_path.name, "research_only": True, "database_imported": False
    }
    (output_dir / f"{stem}.metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="UTC YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="UTC YYYY-MM-DD, exclusive")
    parser.add_argument("--output-dir", default="data/dukascopy")
    args = parser.parse_args()
    print(json.dumps(download_range(date.fromisoformat(args.start),
          date.fromisoformat(args.end), Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
