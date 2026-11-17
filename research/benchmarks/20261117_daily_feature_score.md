# Gold AI daily research benchmark — 17 November 2026

## Result

A first chronological experiment was run on records with complete macro and CFTC inputs and all required lagged-change features.

| Item | Result |
|---|---:|
| Eligible observations | 745 |
| Training observations | 518 |
| Training dates | 2023-12-01 to 2025-12-22 |
| Purged boundary observations | 5 |
| Test observations | 217 |
| Test dates | 2025-12-31 to 2026-11-10 |
| Simple correlation-weighted score accuracy | 46.54% |
| Training-majority baseline accuracy | 47.93% |
| Up precision | 46.15% |
| Predicted up / down | 156 / 61 |
| Mean signed 5-session return | -0.4328% before costs |

Confusion matrix (actual rows, predicted columns):

| | Predicted up | Predicted down |
|---|---:|---:|
| Actual up | 72 | 32 |
| Actual down | 84 | 29 |

## Interpretation

This first feature-combination experiment **did not beat the majority baseline**. Its signed five-session return was negative before spread, slippage, commission and swap. It is not suitable for live signals and is not evidence of profitability.

The score is a simple research diagnostic: each input is standardized using training-only statistics, weighted by its training-set correlation with the binary target, and scored on the later test period. It is not a production ML model. Correlation weighting is vulnerable to correlated inputs, regime changes and small-sample noise.

## Data and leakage cautions

- The future 5-session label is read from `gold_daily_research_labels`; it is never included in the input array.
- The chronological split holds out the final 30%, with five observations purged at the boundary because the target horizon is five sessions.
- Macro and CFTC features use conservative calendar-day lags, but exact historical publication timestamps are not archived. Therefore point-in-time availability is not fully proven.
- The gold daily source is XAUS reference data, not the user's MT5 broker feed.
- No transaction costs or realistic fill assumptions are included.
- The test set is one historical period, not repeated walk-forward validation.

## Decision

Do not deploy this score as a trading signal. Next research steps: repeated rolling walk-forward tests, feature ablation, probability calibration, cost-aware trade simulation and more broker-specific intraday history. Keep execution disabled.
