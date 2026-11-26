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

## Current implementation status

The isolated branch currently contains the following research-only building blocks:

- `backend/trade_workflow.py`: completed-candle level-break confirmation, deterministic trade-plan validation, and an independent fail-closed risk gate.
- `backend/trade_replay.py`: deterministic bid/ask OHLC replay with correct side-specific fills, gap handling, conservative stop-first ambiguous-bar handling, and explicit commission/slippage deductions.
- `backend/tick_replay.py`: tick-by-tick bid/ask replay that checks every archived quote instead of guessing intrabar price order.
- `backend/market_storage.py`: bounded, broker- and symbol-specific reads from the existing `mt5_ticks_research` archive, with pagination and explicit truncation detection.
- `backend/main.py`: research-only `GET /research/trade-replay` endpoint. It requires a verified MT5 candle source and a complete archived bid/ask tick window; it never places orders.
- `backend/test_trade_workflow.py`, `backend/test_trade_replay.py`, and `backend/test_tick_replay.py`: domain-level unit tests.

The Supabase project already contains `mt5_ticks_research` with the columns needed by the collector and replay service, RLS enabled, and broker/time indexes. A read-only count check found zero archived ticks at the time of implementation, so the replay endpoint will correctly return a no-data response until the read-only MT5 tick collector has been run. No Supabase schema or data was changed. The new endpoint is not yet connected to a frontend journal or alerts. The earlier 143-test run predates tick replay. A subsequent GitHub Actions run passed all 151 backend unit tests: https://github.com/Laflame2323/Gold-ai/actions/runs/45391393710.

## Historical data and initial screens without desktop MT5

The user does not have access to a desktop MT5 terminal until the weekend. Research therefore continued using the existing verified Exness trial-source OHLC archive. The MT5 tick collector and tick-level replay still require desktop MT5 and must wait.

A read-only inventory of the connected Gold AI Supabase project found:
- `public.market_candles` contains 248,573 rows across instruments/timeframes.
- Verified Exness trial-source XAUUSDm history includes 9,502 H4 candles (2018-06-28 through 2026-11-19), 50,035 M30 candles (2022-08-26 through 2026-11-19), 50,031 M15 candles, and 32,564 H1 candles.
- The H4 set has one gap longer than 72 hours (largest gap: 4 days).
- The M30 set has 254 gaps longer than 90 minutes, eight longer than 72 hours, and a largest gap of 73.5 hours. Market-session/weekend gaps need an explicit audit.
- `public.mt5_ticks_research` still has zero rows. No tick-level replay or broker-accurate spread analysis is possible yet.

Two preliminary fixed-rule screens were completed:
1. `research/EXNESS_XAUUSDM_H4_INITIAL_SCREEN_2026-11-24.md`: EMA20/EMA50 breakout, strict SELL filter, 1.5 ATR stop, 2R target, next-bar-open entry, 24-bar maximum holding period, and chronological 75/25 split. The 80-trade later holdout showed 55.00% win rate, +0.5879R expectancy, and 2.3653 profit factor before calibrated broker costs. The earlier development block showed 38.43% wins, +0.0911R expectancy, 1.1505 PF, and 23.06R maximum drawdown. This regime divergence is a material warning.
2. `research/EXNESS_XAUUSDM_M30_DAY_TRADING_SCREEN_2026-11-24.md`: the same fixed breakout hypothesis with a 16-M30-candle (8-hour) maximum holding period. On 50,035 verified closed M30 candles, the 417-trade later holdout showed 38.85% wins, +0.0861R expectancy, 1.1518 PF, and 16.9412R maximum drawdown before calibrated costs. Development performance was weaker: 39.38% wins, +0.0498R expectancy, 1.0883 PF, and 32.4009R maximum drawdown. Development expectancy was approximately flat after a hypothetical 0.25 XAUUSD price-unit round-trip deduction and negative at 0.50. The BUY side was more consistent than SELL; SELL was negative in development and only marginally positive in holdout.

Neither screen establishes a verified profit rate. The historical data is OHLC, not tick data; actual bid/ask spread, commission, swap, and slippage are not calibrated. The cost deductions are illustrative only. The two timeframes must not be combined into one claimed Gold AI profit rate.

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
