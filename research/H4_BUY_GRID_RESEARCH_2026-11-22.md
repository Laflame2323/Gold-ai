# H4 BUY parameter sweep — 2026-11-22

Dataset: Dukascopy XAUUSD H4 bid/ask, 15,011 aligned candles.  
This is exploratory research; parameters were searched on the same historical dataset.

## Best high-hit-rate candidate found in the limited grid

- Signal: close > EMA20 > EMA50, close > EMA200.
- Breakout: close above prior 20-candle high.
- Wilder ADX(14) >= 15.
- Wilder RSI(14) between 55 and 75.
- Stop: 2 ATR; target: 0.25R; horizon: 24 H4 bars.
- Entry next bar ask open; exit bid OHLC; stop-first on ambiguous bars.

Full historical result: 215 trades, 81.4% win rate, +0.0174R expectancy, PF 1.094, +3.75R net.

| Period | Trades | Win rate | Expectancy | PF |
|---|---:|---:|---:|---:|
| First 50% | 111 | 76.6% | -0.0428R | 0.817 |
| 50–70% | 43 | 86.0% | +0.0756R | 1.542 |
| 70–85% | 43 | 88.4% | +0.1047R | 1.900 |
| Final 15% | 18 | 83.3% | +0.0417R | 1.250 |

The final 25% contained 46 trades, 84.8% wins, +0.0598R expectancy and PF 1.393. However, the first half of the dataset was loss-making and the full-period expectancy is weak.

## Cost sensitivity

Additional price-unit round-trip cost deductions:

| Extra cost | Expectancy | PF | Net R |
|---:|---:|---:|---:|
| 0.00 | +0.0174R | 1.094 | +3.750R |
| 0.05 | +0.0142R | 1.076 | +3.052R |
| 0.10 | +0.0109R | 1.058 | +2.353R |
| 0.20 | +0.0044R | 1.024 | +0.957R |
| 0.30 | -0.0020R | 0.989 | -0.440R |

## Decision

Although the hit rate exceeds 80%, this is **not a robust profitable candidate**: the edge is very small, weakens materially under extra costs, and the first half of the historical period loses money. Keep it research-only and do not deploy it. This illustrates why an 80% win rate alone is not an adequate acceptance criterion.
