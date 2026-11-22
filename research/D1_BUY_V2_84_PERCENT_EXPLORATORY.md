# D1 BUY candidate v2 — exploratory high-hit-rate filter search

Date: 2026-11-22  
Dataset: Dukascopy XAUUSD bid/ask D1, 2,513 aligned candles (2020-01-01 to 2026-11-22).  
Code: `backend/d1_buy_candidate.py`  
Status: research only; not deployed.

## Candidate rules

Signal after a completed daily bid candle:

- Close > EMA20 > EMA50 and close > EMA200.
- Close breaks the prior 40-candle high.
- Wilder ADX(14) >= 15.
- Wilder RSI(14) between 50 and 80.
- Wilder ATR(14) stop distance = 2 ATR.
- Entry next candle at ask open; exit on bid OHLC.
- Target = 0.5R; maximum holding period = 24 daily candles.
- Stop-first if stop and target are both touched in one candle.
- No overlapping trades.

## Historical result

- 46 trades.
- **84.8% profitable**.
- Expectancy: **+0.2717R per trade**.
- Profit factor: **2.786**.
- Net result: **+12.50R**.

The previous 0.25R / 2 ATR variant under the same Wilder indicator implementation produced 55 trades, 81.8% wins, +0.0227R expectancy and PF 1.125. The 0.5R target variant therefore improved the observed expectancy substantially while retaining a win rate above 80%.

## Chronological slices

| Slice | Trades | Win rate | Expectancy | PF |
|---|---:|---:|---:|---:|
| First 50% | 19 | 84.2% | +0.2632R | 2.667 |
| 50–70% | 11 | 81.8% | +0.2273R | 2.250 |
| 70–85% | 12 | 83.3% | +0.2500R | 2.500 |
| Final 15% | 4 | 100.0% | +0.5000R | No losses |

The final 25% contained 12 trades, 91.7% wins, +0.375R expectancy and PF 5.50.

## Cost sensitivity

Additional round-trip price-unit deductions on top of the historical bid/ask entry/exit model:

| Extra cost | Win rate | Expectancy | PF | Net R |
|---:|---:|---:|---:|---:|
| 0.00 | 84.8% | +0.2717R | 2.786 | +12.500R |
| 0.10 | 84.8% | +0.2695R | 2.767 | +12.399R |
| 0.30 | 84.8% | +0.2651R | 2.730 | +12.196R |
| 0.50 | 84.8% | +0.2607R | 2.694 | +11.993R |

These cost values are illustrative, not calibrated to the user's broker. Win rate is unchanged because the extra cost is applied to trade P/L after exit decisions.

## Critical validation warning

This candidate was found by a parameter grid search across ADX thresholds, RSI bands, breakout lookbacks and target sizes. The later-period results were also inspected during selection. Therefore the apparent 91.7% final-quarter result is **not an untouched holdout** and must not be presented as independent validation. The sample is only 46 trades over almost seven years, with just 12 in the final quarter and 4 in the final 15%.

The original 84.5% result from the earlier exploratory note was also not exactly reproduced by this Wilder-indicator implementation. Indicator parity must be resolved before merging the research conclusions.

## Decision / next validation gate

- Keep this as the current leading D1 BUY research candidate, not a live signal.
- Do not merge into production or execute trades from it.
- Freeze these exact parameters before collecting new data.
- Run forward on the user's actual broker feed in demo mode, recording every signal and realistic spread, commission, slippage, swaps and skipped fills.
- Require at least 30 genuinely new trades as a minimum initial gate (preferably 100+), positive expectancy, PF > 1, and acceptable drawdown before reconsidering.
- It does not validate SELL, H4, H1, M30, M15 or lower timeframes.
- An 84.8% historical result is not a guarantee of future accuracy or profit.
