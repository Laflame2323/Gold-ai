# XAUUSDm M30 archive quality audit

Date: 2026-11-25
Project: Gold AI
Branch: `research/day-trader-workflow-adaptation`
Scope: read-only inspection of Supabase `public.market_candles`
Status: preliminary structural audit; not yet approved for formal strategy replay

## Dataset identity

- Symbol: `XAUUSDm`
- Timeframe: `M30`
- Source: `MT5:Exness-MT5Trial9`
- Rows: 50,035
- First candle open: 2022-08-26 00:30:00 UTC
- Last candle open: 2026-11-19 13:30:00 UTC
- Closed rows: 50,035
- `quality_status='verified'`: 50,035
- Duplicate timestamp excess: 0
- Invalid OHLC geometry: 0
- Off-grid timestamps (not on :00/:30 with zero seconds): 0
- Not-closed rows: 0

The matching Exness H1 archive contains 32,564 rows from 2018-06-28 00:00 UTC to 2026-11-19 13:00 UTC. All rows are closed and marked verified; duplicate timestamp excess is zero. This confirms broad H1 history exists, but does not replace a per-decision point-in-time alignment audit.

## M30 interval findings

A gap is any adjacent timestamp difference greater than 1,800 seconds. Classification below is descriptive, based on whether the interval crosses a Saturday or Sunday in UTC; it is not a verified Exness holiday/session calendar.

| Gap classification | Count | >90 minutes | >72 hours | Largest |
|---|---:|---:|---:|---:|
| Crosses a weekend date | 221 | 221 | 8 | 73.5 hours |
| Does not cross a weekend date | 873 | 33 | 0 | 29 hours |
| Total | 1,094 | 254 | 8 | 73.5 hours |

All observed gap durations were exact multiples of 30 minutes. The SQL audit estimated 24,200 absent 30-minute intervals across all gaps, but this number is **not a missing-data count**: it includes normal market closures, weekend closures, holidays, and shortened sessions.

The largest weekday-only intervals include:
- 2024-12-24 18:00 to 2024-12-25 23:00 UTC: 29 hours.
- 2025-12-24 18:00 to 2025-12-25 23:00 UTC: 29 hours.
- 2024-12-31 21:30 to 2025-01-01 23:00 UTC: 25.5 hours.
- 2025-12-31 21:30 to 2026-01-01 23:00 UTC: 25.5 hours.
- Several 4–5 hour weekday closures on US public holidays.

These patterns are consistent with holiday/early-close sessions, but this must be checked against the historical Exness instrument trading-hours calendar before classifying them as expected.

## Interpretation and restrictions

1. The archive passes the basic row-integrity checks: timestamp uniqueness/order at the SQL grouping level, OHLC geometry, closed status, verified status, and M30 timestamp grid.
2. It does **not** yet pass the complete session-gap audit. The broker's historical session calendar has not been attached to these observations.
3. Do not automatically synthesize candles, forward-fill prices, or interpret every absent interval as a data defect.
4. Do not automatically treat all gaps as safe. The 33 weekday-only gaps over 90 minutes and especially the 29-hour holiday intervals require explicit session classification.
5. The strategy replay must not carry an open simulated trade across a material unclassified data gap. Until a frozen gap policy is implemented, affected trades/segments should be marked censored or excluded with a recorded reason.
6. This audit did not export all 50,035 rows into the local canonical fingerprint routine. Therefore no canonical SHA-256 dataset fingerprint is claimed here. The evaluator's candle payload hash must be computed from the exact frozen M30 and H1 input payload before formal evaluation.
7. No data, schema, RLS policy, or production application was modified.

## Next required checks

- Obtain/freeze the applicable Exness XAUUSDm trading-hours and holiday calendar (including DST changes).
- Classify the 873 weekday-only gaps as normal scheduled closure, holiday/early close, or unexplained gap.
- Add a deterministic session-aware gap policy to the research evaluator; never infer a calendar from strategy outcomes.
- Run a point-in-time H1 availability/alignment audit at every M30 decision timestamp.
- Freeze and record the canonical dataset payload fingerprint and audit report before development/validation replay.
- Keep final test sealed until candidate, costs, data fingerprint, and gap policy are frozen.

## Reproducibility

The figures above were obtained using read-only SQL against `public.market_candles`, filtering exactly on symbol `XAUUSDm`, timeframe `M30`, and source `MT5:Exness-MT5Trial9`. Gap counts use `lag(candle_time)` ordered by candle time and classify a gap as weekend-crossing if its UTC date interval includes Saturday or Sunday.
