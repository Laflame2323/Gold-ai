# Day Trader Skill Adaptation Plan

Date: 2026-11-24
Status: research-only implementation plan
Base: `research/net-expectancy-engine`

## Goal

Adapt the useful engineering workflow from Jakeschincariol/day-trader-skill into the existing Gold AI backend. Do not copy its US-equity trading rules, Yahoo stock data assumptions, NYSE calendar, Alpaca order schema, or long-only restrictions.

Initial instruments:
- XAUUSD
- EURUSD (only after an independent FX data source and symbol metadata are verified)

Gold AI remains a research and decision-support system. No broker order placement, account access, auto-execution, or live trading is part of this work.

## Existing foundations to preserve

- FastAPI/Python backend, Vercel frontend, Supabase private market archives.
- Closed-candle validation and multi-timeframe analysis.
- Authenticated MT5 read-only candle ingestion.
- Existing point-in-time feature builder, triple-barrier research, bid/ask-aware evaluation, and profit-aware research modules.
- Existing production `main` branch and deployed services remain unchanged during this work.

## Adapted workflow

1. **Setup discovery** — reuse existing multi-timeframe analysis and strategy research. A candidate must name its instrument, direction, timeframe, decision timestamp, data source, and strategy version.
2. **Entry confirmation** — evaluate only completed candles. A signal becomes actionable only after its trigger candle closes; no mid-candle or future-candle leakage.
3. **Trade plan** — create a deterministic, immutable plan containing entry rule/price, stop/invalidation, target(s), time expiry, expected reward:risk, and assumptions.
4. **Historical replay** — use chronological, point-in-time data and realistic bid/ask-side fills, spread, commission, slippage, financing/swap where applicable, and conservative intrabar stop/target ordering. Store the input-data/version fingerprint and random seed for reproducibility. Monte Carlo scenarios are stress tests, not calibrated win probabilities.
5. **Independent risk gate** — veto stale/missing data, invalid plans, inadequate net expectancy, excessive per-trade/daily risk, excessive correlated exposure, or disabled/unknown instrument specifications. A model score cannot override a veto.
6. **Monitoring and journal** — record candidates, accepted/rejected decisions, reasons, plan revisions, hypothetical fills, exits, and realized paper results. Alerts monitor conditions only; they do not place orders.

## Instrument/data requirements

- Do not treat XAUS reference prices as broker execution prices.
- Prefer one verified broker feed per instrument for execution-style evaluation; never mix feeds within a single candle series.
- XAUUSD and EURUSD require separate spread, tick/pip, contract-size, lot-step, minimum-volume, commission, swap, and trading-session metadata.
- EURUSD must not be enabled until a trustworthy historical/live candle source and broker-specific symbol metadata are available.
- Live candles must be closed, fresh, timestamp-normalized, gap-checked, and source-labelled.

## Validation gates

- Unit tests for candle closure, freshness, timestamp ordering, stop/target logic, spread-side fills, gaps, and risk vetoes.
- Look-ahead tests that alter future candles and prove earlier decisions/features do not change.
- Chronological train/validation/test splits with purging/embargo for overlapping labels.
- An untouched final holdout; do not tune thresholds or strategy parameters on it.
- Evaluate BUY and SELL separately and report trade count, coverage, net win rate, mean net R, expectancy, profit factor, max drawdown, confidence intervals, and costs sensitivity.
- Compare each candidate against the current baseline and a no-trade baseline.
- Only combine strategies when out-of-sample evidence shows complementary returns; correlated confirmations are not independent votes.
- A 90% win rate is an aspiration, not a release gate. Positive net expectancy, adequate sample size, drawdown control, and out-of-sample stability are mandatory.

## Delivery phases

### Phase 0 — branch and architecture
Create an isolated research branch, document the workflow, map existing modules, and preserve production unchanged.

### Phase 1 — deterministic trade-plan and risk contracts
Add typed, testable domain functions for candidate validation, plan construction, and fail-closed risk checks. Keep them disconnected from the production signal endpoint initially.

### Phase 2 — execution-aware replay
Extend existing bid/ask research to simulate plan entry/stop/target/time-exit logic, including ambiguous bars and gaps. Add reproducible reports.

### Phase 3 — monitoring and journal
Add read-only monitoring and durable decision/plan/outcome records. Never send orders.

### Phase 4 — EURUSD readiness
Add EURUSD only after data-provider and broker-symbol metadata validation, with separate instrument configuration and independent evaluation.

### Phase 5 — controlled UI integration
Expose research-only plans, replay results, risk vetoes, and alerts in the frontend with clear data-source labels. No production deployment until separately reviewed and explicitly approved.

## Explicit exclusions

- No copying stock opening-range rules as-is.
- No Yahoo Finance stock feed as a Forex execution feed.
- No Alpaca order schema or stock position sizing for FX/CFDs.
- No automatic broker execution.
- No claims of 90% accuracy, profitability, or calibrated probabilities without robust evidence.
- No production branch changes in this research task.
