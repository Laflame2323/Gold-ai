# D1 BUY candidate reproducibility and reward/risk sweep

Date: 2026-11-22  
Dataset: Dukascopy XAUUSD bid/ask D1, 2020-01-01 through 2026-11-22 (2,513 aligned candles).  
Research branch: `research/net-expectancy-engine`

## Why this second pass exists

The earlier exploratory note reported 71 trades and an 84.5% win rate for a 0.25R target / 2 ATR stop. Reimplementing the stated EMA, Wilder RSI, Wilder ADX and Wilder ATR rules in the new fixed-rule evaluator did **not** exactly reproduce that result. The reproducible implementation below generated 55 trades at 0.25R with an 81.8% win rate. This discrepancy must be resolved before either result is treated as an established model result. Indicator initialization and calculation differences are a likely source; this is not proof of the cause.

## Locked signal definition used in this pass

After a completed daily bid candle:

- Close > EMA20 > EMA50.
- Close > EMA200.
- Close > highest high of the prior 20 completed candles.
- Wilder ADX(14) >= 20.
- Wilder RSI(14) between 55 and 80.
- Wilder ATR(14) sets the stop distance.
- Enter next daily candle at ask open; exit using bid OHLC.
- Stop-first if stop and target are both touched in the same candle.
- Maximum holding period: 24 daily candles.
- Trades do not overlap.

The new evaluator is `backend/d1_buy_candidate.py`. It is research-only and is not connected to live signal generation or order execution.

## Target sweep with fixed 2 ATR stop

| Target | Trades | Win rate | Expectancy | Profit factor | Net R |
|---:|---:|---:|---:|---:|---:|
| 0.25R | 55 | 81.8% | +0.0227R | 1.125 | +1.25R |
| 0.50R | 46 | 73.9% | +0.1157R | 1.444 | +5.32R |
| 0.75R | 42 | 69.0% | +0.2087R | 1.671 | +8.76R |
| 1.00R | 39 | 66.7% | +0.3333R | 2.000 | +13.00R |
| 1.25R | 37 | 62.2% | +0.3986R | 2.054 | +14.75R |
| 1.50R | 36 | 61.1% | +0.4916R | 2.264 | +17.70R |
| 2.00R | 34 | 47.1% | +0.3962R | 1.748 | +13.47R |

The 1.50R target has the strongest observed expectancy and profit factor in this sweep, while the 0.25R target has the highest hit rate. This is a trade-off, not a universally best setting. The 1.50R setting was selected after inspecting this dataset and is therefore exploratory, not a pristine out-of-sample winner.

## Chronological stability checks

For the 1.50R target, the four chronological slices were:

| Slice | Trades | Win rate | Expectancy | PF |
|---|---:|---:|---:|---:|
| First 50% | 12 | 66.7% | +0.5580R | 2.674 |
| 50–70% | 10 | 50.0% | +0.1284R | 1.257 |
| 70–85% | 9 | 66.7% | +0.6667R | 3.000 |
| Final 15% | 6 | 50.0% | +0.2500R | 1.500 |

The final 25% as a single later-period slice produced 13 trades, 61.5% wins, +0.5385R expectancy and PF 2.40. These samples are too small to prove stability; because the full dataset was already explored, none is a truly untouched holdout.

## Additional round-trip cost sensitivity

At a 1.50R target, after adding the indicated extra price-unit cost on top of the historical bid/ask entry/exit model:

| Extra cost | Win rate | Expectancy | PF | Net R |
|---:|---:|---:|---:|---:|
| 0.00 | 61.1% | +0.4916R | 2.264 | +17.696R |
| 0.10 | 61.1% | +0.4896R | 2.257 | +17.624R |
| 0.20 | 61.1% | +0.4876R | 2.249 | +17.553R |
| 0.30 | 61.1% | +0.4856R | 2.242 | +17.481R |
| 0.50 | 61.1% | +0.4816R | 2.227 | +17.338R |

Costs here are illustrative price-unit deductions, not broker-calibrated commissions or slippage. Win rate does not change because the extra deduction is applied to trade P/L after the exit decision.

## Current decision

- Keep the 0.25R / 2 ATR configuration as the high-hit-rate variant, but flag the prior 84.5% report as not exactly reproduced.
- Keep 1.50R / 2 ATR as a higher-expectancy research variant; observed hit rate is only 61.1%.
- Do not deploy either variant or advertise an 80% Gold AI win rate.
- Resolve indicator parity against the original research script, then collect a genuinely new broker-specific forward sample with pre-registered rules.
- Require materially more than 30 holdout trades, positive expectancy after realistic costs, PF > 1, controlled drawdown, and stable results before considering a production signal.
- This is D1 BUY only. No conclusions about SELL or intraday timeframes follow from these results.
