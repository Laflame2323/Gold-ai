# Exness XAUUSDm M30 day-trading screen — 2026-11-24

## Status and interpretation

Research-only preliminary historical screen. This is not a verified profit rate, a live/demo trading record, a broker-calibrated execution simulation, or approval to trade or deploy. No production code, database rows, schema, or broker orders were changed.

The M30 result is materially weaker than the earlier H4 screen. It shows a small positive historical expectancy before calibrated costs, but a narrow development-period edge and significant drawdown. The strategy is not ready for paper-forward approval, let alone live use.

## Dataset

- Supabase table: `public.market_candles`
- Instrument: `XAUUSDm`
- Source: `MT5:Exness-MT5Trial9`
- Timeframe: M30
- Filters: `is_closed = true`, `quality_status = 'verified'`
- Candles: 50,035
- Coverage: 2022-08-26 00:30 UTC through 2026-11-19 13:30 UTC
- Chronological split: first 75% development; final 25% holdout
- Holdout begins: 2025-10-29 11:30 UTC
- Gaps greater than 90 minutes: 254
- Gaps greater than 72 hours: 8
- Largest observed gap: 73.5 hours

This is broker-origin historical OHLC candle data from an Exness MT5 trial source. It is not bid/ask tick history. The separate `mt5_ticks_research` archive contained zero ticks at the time of the audit. Gaps need a dedicated session/holiday audit before any formal claim.

## Fixed strategy and simulation assumptions

This screen uses the existing Gold AI profitability research rule without tuning against the holdout:

- Signal is evaluated only after a completed M30 candle.
- BUY: close above EMA20, EMA20 above EMA50, and close above the prior 20-candle high.
- SELL: close below EMA20, EMA20 below EMA50, close below the prior 20-candle low, EMA50 falling over five bars, EMA separation of at least 0.15 ATR, and a bearish signal candle.
- Entry: next M30 candle open.
- Stop: 1.5 ATR(14).
- Target: 2R.
- Maximum holding period: 16 M30 candles (8 hours).
- Non-overlapping trades.
- Gap-aware open fills.
- If stop and target are both touched in one OHLC candle, stop is assumed first.
- No spread, commission, swap, or slippage was included in the base result.

The SELL rule is deliberately stricter than BUY. It remains a hypothesis, not a validated improvement.

## Initial results — before broker transaction costs

| Segment | Trades | Win rate | Expectancy | Profit factor | Cumulative R | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Development | 1,333 | 39.38% | +0.0498R | 1.0883 | +66.4289R | 32.4009R |
| Chronological holdout | 417 | 38.85% | +0.0861R | 1.1518 | +35.9099R | 16.9412R |

Holdout annual breakdown:

| Entry year | Trades | Win rate | Expectancy | Profit factor | Cumulative R | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| 2025 (from holdout start) | 61 | 40.98% | +0.1265R | 1.2208 | +7.7172R | 5.4639R |
| 2026 | 356 | 38.48% | +0.0792R | 1.1398 | +28.1928R | 16.9412R |

The holdout is positive before costs, but the development expectancy is only +0.0498R and its profit factor is 1.0883. This is a thin edge that may disappear after realistic trading costs.

## Directional breakdown

| Segment | Side | Trades | Win rate | Expectancy | Profit factor | Cumulative R |
|---|---|---:|---:|---:|---:|---:|
| Development | BUY | 808 | 42.82% | +0.1348R | 1.2514 | +108.9293R |
| Development | SELL | 525 | 34.10% | -0.0810R | 0.8667 | -42.5004R |
| Holdout | BUY | 224 | 41.07% | +0.1304R | 1.2434 | +29.2026R |
| Holdout | SELL | 193 | 36.27% | +0.0348R | 1.0575 | +6.7073R |

SELL is negative in development and only marginally positive in holdout. Do not interpret the holdout reversal as proof that SELL has become reliable. BUY is the more consistent side in this screen, but it still has not passed cost calibration or forward validation.

## Illustrative cost sensitivity

The archive does not contain historical bid/ask quotes at each fill, a verified commission schedule, swaps, or slippage. The following values subtract a hypothetical extra round-trip cost in XAUUSD price units from each trade's gross result. They are sensitivity scenarios only, not measured Exness costs.

| Extra deduction (XAUUSD price units) | Development expectancy | Development PF | Holdout expectancy | Holdout PF |
|---:|---:|---:|---:|---:|
| 0.00 | +0.0498R | 1.0883 | +0.0861R | 1.1518 |
| 0.25 | +0.0010R | 1.0016 | +0.0725R | 1.1260 |
| 0.50 | -0.0479R | 0.9234 | +0.0589R | 1.1010 |
| 1.00 | -0.1457R | 0.7881 | +0.0317R | 1.0529 |

The development block is effectively at break-even with a hypothetical 0.25 price-unit deduction and turns negative at 0.50. This is a major fragility warning. The holdout remains positive in these scenarios, but that does not validate the assumed costs or establish broker profitability.

## Comparison with the H4 screen

The separate H4 screen used 9,502 verified closed candles from 2018-06-28 through 2026-11-19. Its 80-trade later holdout showed 55.00% wins, +0.5879R expectancy, and 2.3653 profit factor before calibrated costs; its earlier development block showed 38.43% wins, +0.0911R expectancy, 1.1505 profit factor, and 23.06R maximum drawdown.

The M30 screen has a larger holdout sample (417 trades) but a much lower win rate (38.85%), weaker expectancy (+0.0861R), and weaker profit factor (1.1518) before costs. Neither timeframe has broker-calibrated transaction costs or tick-level execution validation. The two results must not be blended into one claimed Gold AI profit rate.

## Decisions and next steps

1. Do not promote this M30 rule to the live signal path.
2. Keep BUY and SELL attribution separate. Do not remove SELL or retune the thresholds based on the holdout; any change must be developed on development data and evaluated on a fresh holdout.
3. Audit missing candle periods, market-session boundaries, and timestamp continuity.
4. Obtain broker-specific bid/ask tick history when desktop MT5 becomes available, then replay entries and exits using side-correct bid/ask fills.
5. Calibrate spread by time/session, commission, swaps, slippage, and gap behavior from the intended broker.
6. Run walk-forward evaluation and a prospective demo-forward journal after the historical methodology is frozen.
7. Report sample size, date range, costs, drawdown, and uncertainty alongside every metric. Do not optimize for a 90% win rate at the expense of net expectancy or drawdown.
8. Keep execution disabled, the research branch isolated, and production unchanged.

## Reproduction notes

The data was read from the verified closed M30 archive in ascending `candle_time` order, using the exact symbol and source above. The screen follows the signal, ATR, entry, stop/target, gap, stop-first, and non-overlapping trade rules documented in `backend/profitability_research.py`. The 75/25 split is chronological at `floor(0.75 * 50035)`; no parameter was selected using the holdout. Cost sensitivity is applied after the simulated exit and is not a bid/ask replay.
