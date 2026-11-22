# Cross-timeframe and SELL check for the D1 BUY v2 hypothesis

Date: 2026-11-22  
Feed: Dukascopy XAUUSD bid/ask reference data.  
Research only; no production changes.

## H4 BUY using the same filter family

Rules: close > EMA20 > EMA50, close > EMA200, 40-bar high breakout, Wilder ADX(14) >= 15, Wilder RSI(14) 50–80, 2 ATR stop, 24-bar maximum hold.

| Target | Trades | Win rate | Expectancy | PF | Net R |
|---:|---:|---:|---:|---:|---:|
| 0.25R | 279 | 79.9% | +0.0016R | 1.008 | +0.437R |
| 0.50R | 252 | 67.9% | +0.0313R | 1.100 | +7.878R |
| 0.75R | 233 | 59.2% | +0.0474R | 1.120 | +11.047R |
| 1.00R | 213 | 54.0% | +0.0840R | 1.190 | +17.886R |

The 0.25R setting nearly reaches 80%, but its expectancy and profit factor are effectively breakeven. Higher targets improve expectancy slightly but reduce the hit rate. None is strong enough to promote.

## H4 SELL using mirrored trend/breakout filters

Rules: close < EMA20 < EMA50, close < EMA200, 40-bar low breakout, Wilder ADX(14) >= 15, Wilder RSI(14) 20–50, 2 ATR stop, 24-bar maximum hold.

| Target | Trades | Win rate | Expectancy | PF | Net R |
|---:|---:|---:|---:|---:|---:|
| 0.25R | 164 | 75.0% | -0.0575R | 0.765 | -9.422R |
| 0.50R | 144 | 64.6% | -0.0130R | 0.961 | -1.870R |
| 0.75R | 132 | 56.1% | +0.0159R | 1.040 | +2.100R |
| 1.00R | 127 | 49.6% | +0.0119R | 1.026 | +1.514R |

No SELL configuration here meets the profitability standard.

## D1 SELL spot-check

With a mirrored 40-bar breakdown, EMA20/50/200 bearish trend, 2 ATR stop and 0.5R target:

- ADX >= 15 and RSI 20–50: 24 trades, 58.3% wins, -0.125R expectancy, PF 0.70.
- ADX >= 25 and RSI 25–50: 11 trades, 72.7% wins, +0.0909R expectancy, PF 1.333.

The second result is far too small a sample to establish a SELL edge.

## Decision

- D1 BUY v2 remains the only promising high-hit-rate candidate identified so far.
- H4 BUY at 0.25R has a near-80% hit rate but no meaningful edge after the modeled bid/ask spread.
- H4 SELL is not profitable under the tested mirrored rule.
- D1 SELL is inconclusive and weak at the larger sample setting.
- Do not copy the BUY rules to SELL or other timeframes. Each direction/timeframe needs independent development and future broker-specific validation.
- All figures are exploratory historical diagnostics, not a live 80% win-rate claim.
