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


## Expanded review — three additional XAUUSD research systems

### Source C — tcolja/TradingXAUUSD
Repository: https://github.com/tcolja/TradingXAUUSD
The project describes a tick-first XAUUSD research engine: M1 and higher bars are built from bid/ask ticks; backtests replay ticks with side-correct fills and include spread, latency, slippage, commission and swap. It screens fixed strategy families before allowing genetic search and reserves a final portion of the dataset from the baseline screen.

**Decision:** high-priority research-engine design reference. The key lesson is to prefer tick-level sequencing and real execution costs over guessing intrabar order from OHLC. Do not adopt any strategy until its exact rules and independent results are reproduced. Repository source reviewed via its public project description; implementation not yet audited line by line.

### Source D — akhshayrm/gold-strategy-backtester
Repository: https://github.com/akhshayrm/gold-strategy-backtester
This is a gold-specific minute-by-minute simulator for liquidity sweep + inversion-gap entries. It documents explicit look-ahead truncation tests, random-day audits, bid/ask-side exits and spread costs. Its published case study is especially instructive:
- Raw setup: 9,637 development trades, average -0.172R, PF 0.74.
- A filtered/managed version: 2,685 development trades, +0.303R, PF 1.39.
- Untouched 2025–26 holdout: 776 trades, -0.173R, PF 0.80; reported statistically significant failure (p=0.04).
- A proposed SMT divergence edge reversed after a look-ahead bug was fixed.

**Decision:** adopt its validation principles, not its example strategy. The main value is demonstrating how an attractive development result can fail on unseen data and how future-data leakage can reverse conclusions. Its published holdout result argues strongly against copying a high in-sample win rate.

### Source E — zero-was-here/tradingbot (Aurum)
Repository: https://github.com/zero-was-here/tradingbot
Aurum registers 17 gold strategy forecasts, including time-series momentum, EMA cross, Kalman trend, Donchian breakout, z-score/RSI/Bollinger mean reversion, volatility squeeze, opening-range breakout, macro/risk-off, seasonality, ML, meta-label and RL. Its forecast interface standardizes direction/conviction separately from position sizing and risk.

Its pre-registered H1 walk-forward report uses 18 rolling folds, recorded bid/ask spread, slippage, financing, bootstrap confidence intervals, Deflated Sharpe Ratio and Probability of Backtest Overfitting. Its authors report that neither combined book cleared the pre-registered research gate: walk-forward combined Sharpe -0.26 / -0.17 and DSR 0.003 / 0.007. Its 2025–2026 holdout combined Sharpe was positive at 1.34, but the confidence interval crossed zero. The report therefore concludes no strategy or book had a demonstrated edge.

**Decision:** adopt the common forecast contract, strict point-in-time feature availability, walk-forward model fitting, forecast correlation analysis and multiple-testing corrections. Do not copy the strategy weights or claim that its holdout result proves a robust edge. The report is a useful example of publishing negative research honestly.

### Source F — MarcelNazare/Aurifer
Repository: https://github.com/MarcelNazare/Aurifer
Aurifer tests RSI mean reversion, Donchian breakout, squeeze release, order-flow proxy and a calibrated ML predictor. It documents next-bar execution, session/volatility-aware spread, slippage, commission, ATR stops, trailing/partial exits, time stops, Wilson confidence intervals, bootstrap PnL/Sharpe intervals and break-even win rate.

Its README's example daily ML forecast reports walk-forward AUC 0.481 ± 0.022 and labels the model unvalidated. Its example backtest reports 312 trades and 54.2% wins, but the 95% win-rate interval is 48.6–59.6%, total-PnL interval crosses zero, and it explicitly warns not to trade live. The data feed's minute history is limited, so the documented daily example should not be confused with a robust intraday validation.

**Decision:** adopt calibrated probability reporting, confidence intervals, break-even win-rate comparison, and hard fail-closed behavior when statistical checks do not pass. Do not adopt the current example ML predictor.

### Source G — shrijeet-lokhande/GoldBot
Repository: https://github.com/shrijeet-lokhande/GoldBot
GoldBot describes a gold-specific candle replay engine, market-structure analysis (BOS/CHOCH/sweeps/FVG/OB), multi-timeframe analysis, transparent logistic prediction, no-look-ahead feature pipeline, independent risk gate, paper broker and approval lifecycle. README claims 253+ backend tests and defaults to paper mode.

**Decision:** architecture reference for our operator workflow: completed-bar analysis, transparent forecast fields, separate proposal/risk approval, paper execution ledger, and auditable trade history. Its README and file tree were reviewed, but predictive edge and independent backtest performance were not established in the material inspected. Treat it as engineering inspiration, not a proven profitable strategy.

## Updated priority ranking
1. **Gold-specific execution and validation:** TradingXAUUSD tick replay and gold-strategy-backtester look-ahead/cost audits.
2. **Statistical evaluation:** Aurum and Aurifer confidence intervals, pre-registration, walk-forward, multiple-testing correction and fail-closed rules.
3. **Architecture and trade workflow:** GoldBot's completed-bar replay, transparent prediction, independent risk gate, paper broker and audit journal.
4. **Strategy hypotheses to test:** Quant_Trading's Kalman/momentum/VWAP/structure/Fibonacci/SMC/squeeze/pullback families; Aurum's trend, breakout, mean-reversion and macro families.
5. **Day Trader Skill:** modular pipeline and risk/journal concepts; its stock-specific scanners are not directly portable to gold.

## Next Gold AI research sprint
- Preserve all current production code and existing D1 candidate unchanged.
- Build a research-only common strategy interface: a forecast per completed bar in [-1, +1], with direction/confidence separate from position size.
- Add candidates in small batches, not as a single giant strategy blend.
- Start with Kalman trend, time-series momentum, VWAP, Donchian/structure breakout, squeeze release and liquidity-sweep/FVG reversal.
- Run the same chronological bid/ask simulator for every candidate, using next-bar entries, conservative stop-first resolution, costs, and no future data.
- Record candidate counts and every trial to reduce selection bias. Use a development period, walk-forward folds and a final untouched holdout.
- Compare BUY and SELL separately, then test regime and timeframe breakdowns.
- Only combine candidates if out-of-sample returns add diversification and improve net expectancy/drawdown; never combine merely because indicators agree.
- The 90% target remains aspirational. Do not loosen gates or optimize against the holdout to force 90%.

## Expanded references
- https://github.com/tcolja/TradingXAUUSD
- https://github.com/akhshayrm/gold-strategy-backtester
- https://github.com/zero-was-here/tradingbot
- https://github.com/zero-was-here/tradingbot/blob/main/docs/RESULTS.md
- https://github.com/MarcelNazare/Aurifer
- https://github.com/shrijeet-lokhande/GoldBot

## Source H — TanvirCCC/algo-trading (deep code and trade-log audit)
Repository: https://github.com/TanvirCCC/algo-trading
Reviewed: README, rolling walk-forward script, backtest engine, strategy scanner, ML filter, live signal engine, and published 622-trade CSV. Repository currently advertises 622 OOS trades, 39.4% win rate, +2.13R EV, PF 4.74 and -5.37% max drawdown.

### Independent calculations from the published trade CSV
- Recounted 622 closed trades: 245 wins, 377 losses, 39.39% win rate.
- Recomputed arithmetic mean R from the CSV: +2.129R/trade, matching the headline EV.
- The CSV has 612 shorts and only 10 longs. The 10 long trades total -3.28R; only 2 won. This is not a balanced BUY/SELL system and cannot be adopted as-is for Gold AI.
- The five largest winning trades contribute about 37.1% of the CSV's total net R. The largest is +194.6R. Removing all trades above +10R leaves 602 trades and reduces average expectancy to about +0.79R. The remaining result is still positive in this file, but the headline is materially tail-dependent and requires trade-level execution verification.
- The CSV-derived mean winner is about +6.76R and mean loser about -0.88R. The README's EV illustration uses +5.41R average wins and -1R losses; its PF claim (4.74) also differs from the simple R-sum PF calculated from the CSV (~5.00). These may reflect different sizing/metrics versions, but the published artifacts do not reconcile cleanly and should be reproduced before using any headline statistic.

### Critical implementation issues found
1. **Confirmed same-day daily-bar look-ahead in the published WFV script.** The script builds daily OHLC bars by resampling the complete 5-minute history. For each OOS fold it then selects daily bars with timestamps up to the intraday OOS timestamp. Since a daily bar is timestamped at the start of its day, the daily bias function can read that day's final close, high/low and structure while making a decision earlier in the same day. The OOS call does not set force_neutral_bias=True (that flag is used in the IS grid search), so the OOS result can use future intraday information. This is a blocker: the reported OOS result is not reliable until daily features are shifted/constructed point-in-time and the entire walk-forward run is repeated.
2. **Ambiguous intrabar exits are resolved using candle colour.** When both stop and target are touched in one 5-minute candle, the engine guesses order from whether the candle closed bullish or bearish. Candle colour does not reveal which level traded first. This can incorrectly turn losses into wins. Gold AI should use tick data or conservatively assume stop-first whenever ordering is unknown.
3. **Live ML training uses the published OOS trade log.** The live signal engine loads the OOS CSV and fits a new filter on those outcomes for live use. This may be a reasonable later model update only after that data has actually occurred, but it is not the same frozen model that generated the historical OOS trades. The README's description of the model being trained on the 622 OOS trades should not be presented as evidence that the 622 trades themselves were filtered by a model trained only on earlier data.
4. **The scanner is overwhelmingly short in the published log.** Only 10/622 trades are long. Any claimed general XAUUSD edge needs independent BUY and SELL testing; this result is effectively a short-side result.
5. **The WFV script selects among parameter variants and risk outcomes on each IS segment.** This is a legitimate adaptive research design in principle, but the number of tried configurations and the full selection process must be logged and included in multiple-testing controls. A walk-forward label alone does not remove selection bias.
6. **The backtest/live price model needs broker parity checks.** The published engine uses OHLC fills at the signal's entry/stop/target levels and does not show tick-level bid/ask sequencing in the inspected engine. MT4 live execution uses current Ask/Bid, broker stop levels, lot constraints and real order fills. A candle-close result is not equivalent to a broker-executable fill.

### Decision
**Do not port the signal rules or its headline metrics into Gold AI.** This repository is a useful source of hypotheses (CISD, Asia purge, breaker/IFVG/FVG confluence, London/NY windows, CUSUM regime filter, RF ranking), but its current published performance is blocked by a confirmed point-in-time daily-data leak and ambiguous intrabar ordering. The most valuable lesson is a test case for our own validation engine: automatically detect daily aggregation leakage and prohibit candle-colour guesses for same-bar stop/target sequencing.

### Required re-test if revisited
- Rebuild daily features from only completed prior-day candles (or shift daily aggregates by one full day before using them intraday).
- Run all OOS folds again with the corrected point-in-time feature pipeline.
- Resolve exits with tick-level bid/ask data; if unavailable, stop-first for ambiguous bars.
- Report long and short separately, and report results with the five largest wins removed as a tail-sensitivity check.
- Reconcile the trade CSV, README, window summaries, sizing model and PF/expectancy definitions.
- Freeze the ML model per fold using IS-only data; separately document any later live retraining date and sample.
- Verify net expectancy after intended broker spread, commission, slippage, swap and rejected/partial fills.
