# XAUUSD bid/ask research checkpoint — 2026-11-22

## Scope

- Feed: Dukascopy public historical XAUUSD reference data.
- Period: 2020-01-01 through 2026-11-21 (end date exclusive 2026-11-22).
- H4: 15,011 aligned bid and ask candles.
- D1: 2,513 aligned bid and ask candles.
- Strategy: completed-candle EMA20/EMA50 trend + 20-candle breakout; ATR(14) stop at 1.5 ATR; fixed 2R target; 24-candle maximum holding period.
- Entry is on the next candle open. BUY enters ask and exits bid; SELL enters bid and exits ask. Stop is assumed before target if both are touched in one candle.
- Results below are a local reproduction of the current evaluator logic against the downloaded CSVs. They are research diagnostics, not live results.

## Data validation

- Bid and ask timestamps match for every H4 and D1 candle.
- No ask OHLC component is below its corresponding bid component in this dataset.
- H4 open spread: mean 0.7603, median 0.4600, 95th percentile 1.9540 XAUUSD price units.
- D1 open spread: mean 0.8437, median 0.5040, 95th percentile 2.1756 XAUUSD price units.
- The feed is not the user's broker feed. Separate bid/ask OHLC bars are not tick-synchronized.

## Chronological 75/25 results (spread included; extra commission/slippage set to zero)

| Timeframe | Segment | Trades | Win rate | Expectancy | Profit factor | Net R |
|---|---:|---:|---:|---:|---:|---:|
| H4 | Development | 379 | 34.56% | -0.0422R | 0.9326 | -16.0121R |
| H4 | Holdout | 148 | 42.57% | +0.1876R | 1.3335 | +27.7577R |
| D1 | Development | 67 | 41.79% | +0.2185R | 1.3933 | +14.6399R |
| D1 | Holdout | 29 | 51.72% | +0.5259R | 2.0893 | +15.2507R |

D1 holdout has only 29 trades, below the existing 30-trade minimum research gate. It is not a pass.

## Directional diagnosis

| Timeframe / segment | Side | Trades | Win rate | Expectancy | Profit factor | Net R |
|---|---|---:|---:|---:|---:|---:|
| H4 development | BUY | 235 | 37.87% | +0.0189R | 1.0312 | +4.4439R |
| H4 development | SELL | 144 | 29.17% | -0.1421R | 0.7843 | -20.4560R |
| H4 holdout | BUY | 96 | 45.83% | +0.2853R | 1.5298 | +27.3869R |
| H4 holdout | SELL | 52 | 36.54% | +0.0071R | 1.0118 | +0.3708R |
| D1 development | BUY | 46 | 50.00% | +0.4310R | 1.8996 | +19.8254R |
| D1 development | SELL | 21 | 23.81% | -0.2469R | 0.6585 | -5.1855R |
| D1 holdout | BUY | 21 | 57.14% | +0.7143R | 2.6667 | +15.0000R |
| D1 holdout | SELL | 8 | 37.50% | +0.0313R | 1.0501 | +0.2507R |

SELL is a clear weakness in development data. H4 BUY also has weak development expectancy, despite stronger holdout performance. The strategy is regime-sensitive: H4 calendar-year results were negative in 2020–2023 and positive in 2024–2026.

## Cost sensitivity

Spread is already modeled through bid/ask entry and exit. Additional commission/slippage price-unit deductions were stress-tested at 0.10, 0.25 and 0.50 per round trip. H4 holdout expectancy declined from +0.1876R to +0.1823R, +0.1745R and +0.1614R respectively. These are illustrative deductions, not calibrated broker fees. Swaps, latency, partial fills and spread widening remain unmodeled.

## Engineering correction

Fixed a development-window boundary defect in both single-price and bid/ask simulators: the final allowed signal index could previously create an entry at the exclusive window end and assign an exit candle before entry. Added a regression test covering both simulators.

## Decision

- Do not label the strategy profitable or deploy it.
- Do not claim 80% prediction accuracy.
- Keep BUY and SELL reporting separate; SELL needs redesign using development data only.
- Next validation: broker-specific bid/ask history, rolling walk-forward evaluation, session/regime breakdown, and realistic commission/slippage/swap modeling.
- No production endpoint or live execution was changed.
