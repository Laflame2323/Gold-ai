# Gold AI strategy experiment ledger

Date opened: 2026-11-25
Branch: `research/day-trader-workflow-adaptation`

This is a forward ledger. Historical work is recorded only at the candidate-family level where exact parameter-variant counts can be supported. It is not valid to treat the number of rows below as the total number of parameter combinations previously tried.

| ID | Candidate | Status | Known result / exposure | Exact historical variant count |
|---|---|---|---|---|
| EXP-001 | XAUUSD H4 EMA20/EMA50 breakout | Screened | Development/holdout screen exists; not broker-cost calibrated; regime divergence observed | Unknown; retrospective enumeration required |
| EXP-002 | XAUUSD M30 EMA20/EMA50 breakout | Screened | Development/holdout screen exists; cost sensitivity showed development fragility | Unknown; retrospective enumeration required |
| EXP-003 | XAUUSD D1 BUY candidate | Screened | Candidate was selected after historical data inspection; historical holdout is not pristine | Unknown; retrospective enumeration required |
| EXP-004 | XAUUSD M30 sweep-and-reclaim v1 | Preregistered; evaluator coded; not run on real archive | Final test remains sealed; development/validation replay and data audit pending | 1 preregistered specification; no performance run yet |

## Counting rules from now on

1. Register every distinct signal rule, parameter set, filter combination, timeframe, and materially different cost assumption before running it.
2. Assign a new EXP ID and candidate version for every change. Do not overwrite prior entries.
3. Record data fingerprint, code commit, parameter JSON, development/validation exposure, and whether the final test was opened.
4. The `variant_count` supplied to the M30 evaluator is a manually declared count, not an automatic repository-wide counter.
5. If any prior unlogged variants are discovered, increase the declared count and retain the multiple-testing warning. Never retroactively erase failed variants.
6. No candidate may be promoted on win rate alone. Evaluate net expectancy after costs, profit factor, drawdown, uncertainty intervals, and stability.

## Current multiple-testing statement

At least three distinct historical candidate families have already been screened (EXP-001 through EXP-003). Their full parameter-search histories are not reconstructed, so the total number of variants tried is **unknown**. The M30 sweep-and-reclaim specification is the fourth registered candidate family and has not yet been performance-tested. Results from previously inspected samples must be treated as exploratory, not as a clean independent confirmation.

The final M30 test remains sealed until data quality, session costs, candidate freeze, and the historical experiment count are documented.


## Data-audit update — 2026-11-25

A read-only structural audit of the existing Exness `XAUUSDm` M30 archive has been documented in `research/XAUUSDM_M30_DATA_QUALITY_AUDIT_2026-11-25.md`.

- 50,035 M30 rows; all marked closed and verified.
- No duplicate timestamp excess, invalid OHLC geometry, or off-grid M30 timestamps were found.
- 1,094 intervals exceed 30 minutes; 873 do not cross a weekend date, and 221 do.
- Thirty-three non-weekend-crossing intervals exceed 90 minutes; the largest is 29 hours.
- These are interval observations, not a count of confirmed missing data. A broker holiday/session calendar is still required.
- No full canonical payload SHA-256 fingerprint has yet been computed from the frozen M30+H1 export.

EXP-004 therefore remains **not formally evaluated**. Do not open the final test based on this preliminary structural audit alone.
