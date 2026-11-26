# Gold AI Multi-Horizon Research Specification

Status: proposed baseline; research-only. Branch: `research/day-trader-workflow-adaptation`.

## Scope
- Primary decision horizons: H1 observations with 1-, 2-, and 4-bar (1h, 2h, 4h) outcomes.
- Secondary decision horizons: M15 observations with 1- and 2-bar (15m, 30m) outcomes.
- Instrument: XAUUSDm research archive only until independent feeds are separately audited.
- No order execution, production model promotion, or live-trading connection.

## Label specification v0.1
- Candle timestamps are UTC Unix seconds marking bar opens.
- A decision is made only after the decision candle closes.
- Entry reference is the next bar open; the next bar must begin exactly at the decision close.
- ATR is Wilder ATR(14), calculated through and including the completed decision candle.
- Upper/lower first-passage barriers are entry +/- 1.0 ATR.
- LONG (+1): upper barrier is reached first.
- SHORT (-1): lower barrier is reached first.
- NEUTRAL (0): neither barrier is reached and timeout close is within +/- 0.10 ATR, or both barriers are touched within one OHLC bar.
- Timeout outcomes beyond +/- 0.10 ATR are labelled directionally by the sign of the gross close-to-entry move.
- Missing bars or session gaps inside the event invalidate the event; they are not silently bridged.
- The label end timestamp is retained for purging overlapping samples.
- OHLC cannot resolve the order of two barriers touched in one candle. Such samples are neutral in v0.1; tick data can later resolve them.
- Labels are gross-price research targets. Spread, commission, slippage and swap are not yet deducted; this is not a tradability label.

## Feature policy
Every feature must be computed using information available at or before the decision timestamp. Higher-timeframe candles are available only after their close. Macro and COT features must be aligned to actual public release/availability timestamps, not reference periods. Rolling normalisation and imputation are fitted on training folds only.

## Evaluation policy
- Chronological expanding walk-forward folds.
- Purge any training sample whose label end time reaches or overlaps the next evaluation block.
- Embargo at least the maximum label horizon at each fold boundary.
- Keep a final chronological holdout untouched until all model and threshold decisions are frozen.
- Fit transforms and feature selection on training data only; calibrate probabilities on a separate validation block.
- Report per-horizon and per-direction class counts, balanced accuracy, precision/recall, Brier score, log loss, calibration, coverage, and net expectancy after realistic costs.
- Compare against majority-class, simple directional, and no-trade baselines.
- Report block-bootstrap uncertainty and cost sensitivity.
- Do not interpret class probabilities as trade confidence until calibrated and externally checked.

## Promotion gates
No model is considered a successful trading candidate solely because of classification accuracy or win rate. Require adequate sample size, stable out-of-sample performance, positive net expectancy after costs, acceptable drawdown, robust cost sensitivity, and paper-monitoring evidence. A failed candidate is a valid research result.

## Implementation notes
Existing research modules already include point-in-time alignment, multi-timeframe features, a causal SMC proxy set, baseline ML, gradient boosting, triple-barrier meta-labelling, and bid/ask replay. This specification and the new label generator are intended to fill the gap between the existing generic meta-label evaluator and distinct H1/M15 directional research tasks.
