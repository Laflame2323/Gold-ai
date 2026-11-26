# Exness XAUUSDm H4 historical screening — 2026-11-24

## Status

Research-only preliminary screen. This report is not a verified profit rate, a live trading record, or approval to deploy. No production code, database rows, schema, or broker orders were changed.

## Dataset

- Supabase table: `public.market_candles`
- Instrument: `XAUUSDm`
- Source: `MT5:Exness-MT5Trial9`
- Timeframe: H4
- Filters: `is_closed = true`, `quality_status = 'verified'`
- Candles: 9,502
- Coverage: 2018-06-28 00:00 UTC through 2026-11-19 08:00 UTC
- Chronological split: first 75% development; final 25% holdout
- Holdout begins: 2025-05-27 20:00 UTC
- Data continuity: 1,234 gaps longer than 4 hours (mostly expected market closures); one gap longer than 72 hours; largest gap 4 days. The long gap needs review before a formal test.

This is broker-origin historical OHLC candle data from an Exness MT5 trial source. It is not tick data. The separate `mt5_ticks_research` table currently contains zero ticks.

## Fixed strategy tested

Used the existing research rule from `backend/profitability_research.py` without changing its parameters:

- Signals are evaluated only after a completed H4 candle.
- BUY: close above EMA20, EMA20 above EMA50, and close above the previous 20-candle high.
- SELL: close below EMA20, EMA20 below EMA50, close below the previous 20-candle low, falling EMA50 over five bars, EMA separation of at least 0.15 ATR, and a bearish signal candle.
- Entry: next H4 candle open.
- Stop: 1.5 ATR(14).
- Target: 2R.
- Maximum holding period: 24 H4 candles.
- Non-overlapping trades.
- Gap-aware open fills; if stop and target are both touched within one OHLC candle, stop is assumed first.

## Initial result — before broker transaction costs

| Segment | Trades | Win rate | Expectancy | Profit factor | Cumulative R | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Development | 242 | 38.43% | +0.0911R | 1.1505 | +22.04R | 23.06R |
| Chronological holdout | 80 | 55.00% | +0.5879R | 2.3653 | +47.03R | 4.10R |

Directional breakdown:

| Segment | Side | Trades | Win rate | Expectancy | Profit factor |
|---|---|---:|---:|---:|---:|
| Development | BUY | 157 | 45.22% | +0.2858R | 1.5273 |
| Development | SELL | 85 | 25.88% | -0.2686R | 0.6280 |
| Holdout | BUY | 51 | 50.98% | +0.4815R | 2.0187 |
| Holdout | SELL | 29 | 62.07% | +0.7750R | 3.1733 |

The development SELL result is poor, while holdout SELL is much stronger. That reversal is a warning about regime dependence, not proof that SELL has become reliable. The holdout is one later market regime and must not be treated as a guarantee.

## Illustrative cost sensitivity

The candle archive does not provide the historical bid/ask spread at each fill, commission schedule, swaps, or slippage. To understand sensitivity only, extra round-trip price deductions were applied to simulated P/L. These are assumptions, not measured Exness costs.

| Extra deduction (XAUUSD price units) | Development expectancy | Development PF | Holdout expectancy | Holdout PF |
|---:|---:|---:|---:|---:|
| 0.00 | +0.0911R | 1.1505 | +0.5879R | 2.3653 |
| 0.25 | +0.0741R | 1.1203 | +0.5819R | 2.3435 |
| 0.50 | +0.0571R | 1.0911 | +0.5759R | 2.3220 |
| 1.00 | +0.0231R | 1.0357 | +0.5640R | 2.2796 |

Win rate in this table is not a broker-calibrated net win rate; cost deductions are applied after the exit decision. Actual spread, commissions, swaps, and slippage still need to be measured.

## Interpretation and next steps

1. This is a promising reason to continue research, not a reason to trade the strategy.
2. The 55% holdout win rate is based on 80 H4 trades from one later period. It is not Gold AI's overall profit rate.
3. Development performance is much weaker and has a 23.06R maximum drawdown. The difference between development and holdout suggests strong regime dependence.
4. Do not advertise 90% accuracy, 55% live accuracy, or a guaranteed profit rate.
5. Next run a separate M30 day-trading screen with the same pre-registered rules and a proper chronological holdout; do not tune on the holdout.
6. Before any profitability claim, validate the strategy on tick-level bid/ask data, calibrate spread/commission/swap/slippage, inspect missing-data periods, and run a longer forward demo sample.
7. Keep BUY and SELL performance separate. Any SELL filter change must be developed on development data only and then tested on a fresh holdout.
8. No live execution is enabled. No merge to `main` or production deployment is authorized by this research.

## Reproduction notes

The strategy definition and simulator are in `backend/profitability_research.py`. The data query must filter the dataset exactly as specified above and sort by `candle_time` ascending. The split is chronological at `floor(0.75 * candle_count)`. Development trades are prevented from entering the holdout window. The cost-sensitivity deductions are applied to each trade's gross price P/L before dividing by its ATR risk.
