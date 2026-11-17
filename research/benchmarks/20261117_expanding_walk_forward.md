# Gold AI — expanding-window walk-forward diagnostic

Date: 17 November 2026

## Setup

- 745 eligible daily observations with macro, CFTC, lagged-change features and a 5-session target.
- Four chronological test folds, each trained only on earlier observations.
- Five observations embargoed between each training cutoff and its test window.
- Each fold's feature means, standard deviations and feature/target correlations are calculated from that fold's training set only.
- Predictions are a correlation-weighted standardized score; positive score means up, otherwise down.

## Fold results

| Fold | Test dates | Rows | Score accuracy | Training-majority accuracy | Up precision | Signed return before costs |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2025-12-31 to 2026-03-13 | 50 | 50.00% | 62.00% | 68.75% | -0.4800% |
| 2 | 2026-03-16 to 2026-05-26 | 50 | 48.00% | 44.00% | 45.24% | -0.1035% |
| 3 | 2026-05-27 to 2026-08-06 | 50 | 54.00% | 56.00% | 55.81% | -0.1145% |
| 4 | 2026-08-07 to 2026-11-10 | 67 | 34.33% | 34.33% | 28.57% | -0.8007% |

Across all 217 test observations, the score achieved approximately **45.62% accuracy**, compared with approximately **47.93%** for the fold-specific training-majority baseline. The weighted mean signed five-session return was approximately **-0.4081% before costs**.

## Decision

The feature score fails to beat the simple baseline overall and has negative signed returns in every fold. The final fold is particularly weak. Do not use it for live or demo trade signals. It is a research diagnostic only.

This does not establish that macro or CFTC data are useless; it shows this simple weighting method does not extract reliable predictive value from this sample. Next work should test feature ablations, regularized models and calibrated probabilities using nested chronological validation, then add spread, slippage, commission, swap and broker-specific execution assumptions.

## Limitations

Calendar-day lags are conservative but historical release timestamps are not fully archived. The gold source is XAUS reference data, not the user's MT5 broker feed. The test period is short and the folds are adjacent; results are not proof of future performance.
