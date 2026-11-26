# Gold AI point-in-time / look-ahead leakage audit

Date: 2026-11-25
Scope: reviewed research modules on `research/day-trader-workflow-adaptation`.
Status: source-level review only; not a substitute for a full data-pipeline audit.

## Findings by module

| Module | Feature / decision | Availability check | Finding |
|---|---|---|---|
| `point_in_time_features.py` | Higher-timeframe candle alignment | Lower decision time is lower bar open + lower timeframe; HTF bar is eligible only when HTF open + HTF duration <= decision time | Causal for correctly timestamped, session-aligned input. Caller must supply bar-open Unix timestamps and correct timeframe/session boundaries. |
| `d1_buy_candidate.py` | EMA20/50/200, ATR14, RSI14, ADX14 | Indicator arrays are built sequentially; each output at index i depends on values at or before i. Signal uses `rows[index]`; breakout high uses `rows[index-breakout_period:index]`; entry uses next bar open. | No direct future-row reference found in the reviewed indicator and signal code. Signal is based on completed current bar only if caller supplies closed bars. |
| `profitability_research.py` | EMA20/50, ATR14, prior 20-bar breakout | `_signal` receives history through current index; prior range excludes current signal candle; entry uses index + 1 open. | No direct future-row feature use found. Requires closed-candle input and correct bar timestamps. |
| `bid_ask_profitability_research.py` | Bid/ask fills and exits | Signal is computed from bid history through signal index; next bar is used for entry; bid exits BUY / ask exits SELL. | No direct future-row signal use found. OHLC bid/ask extremes are not tick-synchronized; execution path remains an approximation. |
| `m30_sweep_reclaim_research.py` | Prior 20-bar range, ATR14, reclaim candle | Prior range is rows before signal index; ATR includes signal candle, which is known at close; entry uses next M30 open. | No direct future M30 feature use found. Caller must provide closed M30 bars with bar-open timestamps. |
| `m30_sweep_reclaim_research.py` | H1 EMA20/50 and slope context | H1 rows are filtered by `h1_open + 3600 <= M30_decision_close` before EMA/slope calculation. | Explicitly excludes unfinished H1 bars. Requires H1 timestamps to represent bar opens in UTC seconds. |

## Specific leakage controls

1. **Higher timeframe:** H1 values are available only after their own close. The unit test adds an unfinished future H1 bar and verifies that the context does not change.
2. **Breakout range:** Prior highs/lows are sliced to exclude the signal candle itself.
3. **Entry timing:** All reviewed candidate simulators enter no earlier than the next candle open.
4. **Chronology:** Research blocks are time-ordered. The M30 sweep candidate excludes 12 bars around each split and simulates each block separately so a trade cannot cross a split.
5. **Indicators:** EMA and Wilder-style indicator loops update forward one bar at a time. No centered rolling windows or backward fills were found in these reviewed modules.

## Remaining risks / unverified assumptions

- The source-level review cannot prove that upstream database rows are closed, correctly timestamped, UTC-normalized, unique, or correctly assigned to trading sessions. Those properties need a dataset audit and fingerprint.
- The M30 sweep evaluator validates strictly increasing timestamps and OHLC consistency, but a full gap/session/weekend audit is still required before replay.
- The D1 evaluator computes indicators across the full array, but the implementation is sequential and index-causal; future rows do not feed earlier outputs. A regression test should still compare truncated-series and full-series features at identical earlier timestamps.
- No feature-level perturbation suite has yet been run across every strategy module.
- This review does not cover every production chart, alert, model-training, or API feature in the repository.
- Historical strategy variants and parameter combinations previously explored are not yet fully enumerated. Do not interpret the evaluator's manually supplied `variant_count` as a complete experiment ledger.

## Decision

No obvious direct look-ahead access was found in the reviewed candidate feature paths. This is a provisional source review, not a clean bill of health for the entire repository. The final M30 test remains sealed until the dataset gap audit, cost calibration, candidate freeze, and variant ledger are complete.
