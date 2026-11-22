# D1 BUY high-hit-rate candidate — exploratory research (2026-11-22)

## Candidate rule

- Instrument: XAUUSD.
- Timeframe: D1 only.
- Direction: BUY only.
- Signal after completed daily candle:
  - close > EMA20 > EMA50;
  - close > EMA200;
  - close breaks the previous 20-candle high;
  - ADX(14) >= 20;
  - RSI(14) between 55 and 80.
- Entry: next daily candle ask open.
- Exit: bid OHLC, ATR(14) stop = 2.0 ATR, target = 0.25R, maximum holding period = 24 daily candles.
- If stop and target are both touched in one candle, stop is assumed first.
- The separate Dukascopy bid/ask OHLC streams are used. This includes a historical spread approximation, but not tick-synchronized fills.

## Exploratory results

On the 2020-01-01 to 2026-11-22 reference dataset:

- Total: 71 trades, 84.5% profitable, +0.0563R expectancy, PF 1.364, +4.00R net.
- Four chronological segments:
  - First 50%: 24 trades, 83.3% profitable, +0.042R expectancy, PF 1.25.
  - 50–70%: 19 trades, 84.2% profitable, +0.053R expectancy, PF 1.333.
  - 70–85%: 18 trades, 83.3% profitable, +0.042R expectancy, PF 1.25.
  - Final 15%: 10 trades, 90.0% profitable, +0.125R expectancy, PF 2.25.

## Cost sensitivity

The bid/ask entry and exit model already includes the reference feed's spread approximation. Additional round-trip price deductions were tested:

| Extra price-unit cost | Profitable trades | Expectancy | Profit factor | Net R |
|---:|---:|---:|---:|---:|
| 0.00 | 84.5% | +0.0563R | 1.364 | +4.00R |
| 0.05 | 84.5% | +0.0553R | 1.357 | +3.93R |
| 0.10 | 84.5% | +0.0543R | 1.350 | +3.86R |
| 0.20 | 84.5% | +0.0523R | 1.336 | +3.71R |
| 0.30 | 84.5% | +0.0502R | 1.322 | +3.57R |

These are illustrative costs, not calibrated to the user's broker. Actual commission, slippage, swaps and execution conditions still need modeling.

## Important limitations

1. This is a parameter-selected exploratory candidate, not an untouched prospective test. The dataset has already been examined during strategy development; the later segments must not be presented as independent, pristine validation.
2. Sample size is only 71 trades across almost seven years. The final segment has only 10 trades.
3. The target is just 0.25R while the stop is 2R. High hit rate does not mean large profits; a small number of losses can erase many wins.
4. It is D1 BUY only. It does not validate H4, M15, SELL, or all timeframes.
5. Dukascopy is a reference feed, not the user's broker execution feed. Separate OHLC streams are not tick synchronized.
6. No live trading or production code was changed.

## Decision

Keep this as a research candidate only. Do not promote it to a live Gold AI signal until it passes a genuinely future, broker-specific demo-forward test with pre-registered rules, sufficient trades, realistic costs, and risk/drawdown limits. The 80% target has not been achieved for Gold AI as a whole.
