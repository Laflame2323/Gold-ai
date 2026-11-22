# External Model Research Audit — Day Trader Skill and Quant Trading

Date reviewed: 2026-11-22
Status: research-only; no production strategy or execution changes.

## Objective
Evaluate external open-source trading systems for ideas that can improve Gold AI. The aspirational research target is a 90% profitable-trade rate, but this is not a forecast or guarantee. Every candidate must also demonstrate positive net expectancy, adequate trade count, controlled drawdown, and out-of-sample stability after realistic broker costs.

## Source A — Jakeschincariol/day-trader-skill
Repository: https://github.com/Jakeschincariol/day-trader-skill
License stated by repository: MIT.
Design: eleven modular Claude skills for scanning, news, entry timing, exit planning, historical simulation, risk, sizing, broker approval, alerts, earnings analysis, and public congressional-trade tracking.

### Useful ideas to adapt
- Separate the pipeline into explicit stages: setup discovery -> confirmation -> trade plan -> historical evaluation -> risk gate -> monitoring -> journal.
- A dedicated risk gate should veto trades independently of the signal model.
- Save a complete trade plan before entry: direction, entry trigger, invalidation/stop, target, expiry/time exit, and sizing.
- Use deterministic replay with fixed seeds and stored inputs so results can be reproduced.
- Keep paper trading and explicit human approval as defaults.
- Record all vetoes, missed trades, fills, and exit reasons for model evaluation.

### Important limitations
- The scanner's rules/universe are US-equity focused (Nasdaq-listed stocks, opening-range breakouts, daily stock setups); not directly suitable for XAUUSD.
- The Time Machine uses a 60-day pool of 5-minute stock bars and random resampling by time-of-day. This is a scenario simulation, not a calibrated probability forecast. Its own documented TSLA example gave target-first 29.4%, stop-first 25.5%, and 45.1% neither; historical rule replay fired 33 times with 13 targets, 15 stops, and 5 neither. The example itself says it was close to a coin flip.
- The simulator models OHLC bars and stop-first ordering; it cannot guarantee real fills, and gaps can exceed stop prices.
- Earnings analysis and congressional-trade tracking are irrelevant to the initial XAUUSD model.
- Popularity, stars, and a permissive license do not establish predictive edge.

### Decision
Do not copy its stock signals or claim its simulations prove profitability. Adapt the modular workflow, risk veto, deterministic replay/reporting, explicit plan, and trade journal concepts only after implementing gold-specific data and tests.

## Source B — vrd07/Quant_Trading
Repository: https://github.com/vrd07/Quant_Trading
License stated by repository: MIT.
Design: MT5 gold/FX/crypto system with 13 strategy modules, regime classification, confluence filtering, multi-timeframe data, trade journaling, and a sequential risk engine.

### Gold strategies worth independently testing
- Kalman regime / trend-mean-reversion hybrid
- Momentum with ROC and ADX confirmation
- VWAP mean reversion
- Structure-break retest
- Fibonacci 50–61.8% retracement
- SMC order block with fair-value-gap confluence
- Asia-session range fade
- Volatility squeeze breakout
- EMA trend + stochastic pullback

### Useful architecture ideas
- Regime-aware strategy selection (TREND / RANGE / VOLATILE), with hysteresis/smoothing to avoid rapid flips.
- Confluence gate that requires independent evidence for selected strategy families, while allowing only explicitly validated standalone strategies.
- Risk engine with kill switch, circuit breaker, daily loss/drawdown limits, exposure limits, news blackout, and ATR-based sizing.
- Per-strategy and per-regime attribution in a durable trade journal.
- Backtest/live parity: use the same signal, confluence, and risk code paths where possible.
- Retire strategies when walk-forward evidence fails rather than repeatedly retuning them.

### Reported results — treated as claims to reproduce, not verified facts
The repository reports (Jan 2025–Mar 2026) XAUUSD results for Kalman Regime: PF 1.15, 1,252 trades, +4.62% return, -2.74% max drawdown; Momentum: PF 1.10, 2,023 trades, +4.68%, -5.33% max drawdown; Breakout: PF 1.02, 907 trades, +1.23%, -5.60% max drawdown. Its June 2026 15m report shows XAUUSD Squeeze Breakout at 36.7% win rate / PF 1.50 / 283 trades and Stoch Pullback at 33.4% / PF 1.22 / 658 trades. The report explicitly says these strategies fail some deployment gates and are diversifiers, not stand-alone gate-passers.

### Important limitations
- These are self-reported repository backtests; we have not independently reproduced the runs or verified live performance.
- Several strategies have low hit rates despite positive profit factors, demonstrating why win rate alone is insufficient.
- The system includes live execution and a prop-firm setup; we must not import its live-order functionality or risk settings into Gold AI.
- Different broker feeds, symbol specifications, spreads, commissions, swaps, and execution conditions can materially change results.

### Decision
This is the more directly relevant research source because it targets XAUUSD. Port strategy concepts one at a time into a research-only candidate registry, then reproduce on our Dukascopy bid/ask history and later on the intended broker's data. Do not copy its reported metrics as Gold AI results.

## Gold AI integration plan
1. Create a strategy registry with source, hypothesis, market regime, timeframe, direction, parameters, and implementation status.
2. Add candidates individually: Kalman/regime, momentum, VWAP, structure-break retest, Fibonacci pullback, SMC+FVG, Asia range fade, squeeze breakout, stochastic pullback.
3. Use common bid/ask-aware execution simulation with spread, commission, slippage, swaps where applicable, conservative intrabar stop/target ordering, and gap handling.
4. Require chronological walk-forward testing, untouched final holdout, sufficient trades, and stability across market regimes. Avoid optimizing on the final holdout.
5. Evaluate BUY and SELL separately and test D1/H4/H1/M30/M15/M5 independently before considering any ensemble.
6. Combine only candidates with demonstrably complementary returns. Use out-of-sample correlation and regime-conditioned weights; do not count correlated confirmations as independent evidence.
7. Track win rate, average win/loss, expectancy in R, profit factor, max drawdown, trade count, exposure, and confidence intervals. A 90% win rate with negative expectancy is a failure.
8. Keep all external strategy imports research-only. No production deployment or live trading without separate validation and explicit approval.

## Current Gold AI baseline
The existing D1 BUY candidate that reached 84.5% win rate (71 trades) and the newer D1 BUY v2 candidate reported at 84.8% (46 trades) are exploratory, data-selected results. Neither is an independently validated live hit rate. The second result has a particularly small sample. These should remain baselines for comparison, not be combined blindly with external strategies.

## References
- https://github.com/Jakeschincariol/day-trader-skill
- https://github.com/vrd07/Quant_Trading
- https://github.com/vrd07/Quant_Trading/blob/main/RESEARCH_PAPER.md
- https://github.com/vrd07/Quant_Trading/blob/main/reports/new_strategies_backtest_2026-06-27.md
