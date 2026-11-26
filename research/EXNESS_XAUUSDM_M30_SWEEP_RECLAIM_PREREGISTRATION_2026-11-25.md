# XAUUSD M30 sweep-and-reclaim candidate — preregistration

Date: 2026-11-25
Status: hypothesis specification only; NOT backtested
Branch: `research/day-trader-workflow-adaptation`

## Purpose

The EMA breakout screens were weak or unstable across development and later periods. This document freezes a structurally different candidate before testing: a failed-breakout / liquidity-sweep-and-reclaim setup. It is not assumed to be profitable, and the words “liquidity sweep” describe observable candle behaviour only; OHLC data cannot prove institutional order flow.

## Data and scope

- Instrument: Exness trial-source `XAUUSDm` only.
- Primary timeframe: M30.
- Context timeframe: H1, used only when its candle is fully closed at the M30 decision time.
- Data: verified, closed candles from the existing archive; one source per series.
- No EURUSD transfer or cross-instrument generalisation.
- No live execution or production signal integration.

Before any evaluation, verify exact symbol/source/timeframe coverage, duplicate timestamps, invalid OHLC rows, and session/weekend gaps. If the archive cannot support point-in-time H1 alignment, the candidate must be marked insufficient-data rather than filling missing context.

## Frozen signal hypothesis

Evaluate only after an M30 candle closes. Calculate ATR(14) and the prior 20 completed M30 candle range using candles strictly before the signal candle.

- Bullish sweep-and-reclaim: the signal candle's low trades below the prior 20-candle low, but its close finishes back above that prior low.
- Bearish sweep-and-reclaim: the signal candle's high trades above the prior 20-candle high, but its close finishes back below that prior high.
- Require the reclaim candle's real body to be at least 35% of its full high-low range. A zero-range candle is invalid.
- Require the close to be in the upper 35% of the candle range for BUY, or lower 35% for SELL.
- H1 context is descriptive and point-in-time: record H1 EMA20/EMA50 ordering and slope, but do not use it to veto signals in the first baseline run. This avoids silently turning the first test into a parameter search.
- If both bullish and bearish conditions somehow qualify on the same candle, reject the signal as ambiguous.
- One open research trade at a time; no overlapping positions.

These are fixed research rules, not a claim that a sweep is a reliable reversal signal.

## Trade simulation contract

- Entry: next M30 candle open.
- Initial stop: beyond the sweep extreme by 0.10 ATR(14), with minimum distance 0.50 ATR and maximum distance 2.00 ATR; reject if outside these bounds.
- Target: fixed 1.5R for the first baseline.
- Maximum holding period: 12 M30 candles (6 hours); then exit at the close.
- Model opening gaps at the next available open.
- If stop and target are both touched in one OHLC candle, assume stop first.
- If the next bar opens beyond the stop, use the open as the adverse fill; never grant a fill at a price the market has crossed.
- Base OHLC results must be labelled pre-cost. Follow with explicit cost sensitivity, then broker bid/ask tick replay when desktop MT5 collection becomes available.
- Do not treat Exness trial OHLC as bid/ask execution history.

## Evaluation protocol

1. Audit and freeze the input dataset fingerprint and data-quality report.
2. Use chronological 60% development / 20% validation / 20% final test, with a 12-bar embargo around boundaries and no trade allowed to cross a split.
3. Use development only to diagnose the fixed rule. Any change to thresholds creates a new candidate version and requires a fresh validation/test period.
4. Use validation only for a single pre-declared decision: retain the fixed candidate unchanged or reject it. Do not tune multiple filters against validation.
5. Open the final test once after the candidate and cost assumptions are frozen. If test performance is poor, record rejection; do not retune on that test.
6. Report BUY and SELL separately, plus combined results: number of trades, coverage, win rate, mean/median net R, expectancy, profit factor, max drawdown, longest losing streak, holding time, and cost sensitivity.
7. Include confidence intervals or uncertainty estimates and compare against no-trade and simple baseline alternatives.
8. Require adequate sample size and stability across time blocks. A high win rate alone is not a pass criterion.

## Stop conditions

Reject or pause the experiment if:
- timestamps are duplicated, out of order, or inconsistent with bar duration;
- material session gaps are silently bridged;
- the higher-timeframe context uses an unfinished H1 candle;
- too few independent trades exist to support a useful estimate;
- results depend on a small number of outliers or one market regime;
- modest plausible transaction costs erase expectancy;
- any feature or label uses information unavailable at the decision time.

## Current status and next action

No strategy performance has been measured from this specification. The existing causal feature module contains sweep/reclaim-style candle proxies, but this candidate still needs a dedicated deterministic evaluator, unit tests, a data-gap audit, and a frozen chronological replay. It must not be described as a winning strategy or included in any Gold AI profit-rate claim.

Production `main`, the deployed application, database schema/data, and broker execution remain untouched.
