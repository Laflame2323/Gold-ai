# M30 sweep-and-reclaim implementation clarifications

Date: 2026-11-25
Applies to: `m30-sweep-reclaim-v1`
Status: frozen before any performance evaluation; clarification only, not a parameter search.

The original preregistration remains the governing hypothesis. These points resolve implementation ambiguities without adding signal filters:

1. **Decision timestamp:** M30 candle timestamps are bar-open Unix seconds. The decision is made at `M30 open + 1800 seconds`. An H1 candle is eligible only when `H1 open + 3600 <= M30 decision close`.
2. **H1 slope field:** record the difference between the current completed-H1 EMA20 and the immediately preceding completed-H1 EMA20. It is descriptive only and never vetoes a trade. EMA20/EMA50 ordering is also descriptive.
3. **Stop-distance measurement:** the 0.50–2.00 ATR constraint is measured from the actual next available M30 entry open to the stop beyond the sweep extreme, not from the signal candle close.
4. **Holding-period count:** the entry M30 candle is holding candle 1. The maximum of 12 candles therefore includes the entry candle; the time exit is at the close of candle 12.
5. **Replay boundary:** a trade must be fully resolved inside its chronological evaluation segment. A trade still open at a segment boundary is censored and excluded rather than carried into the next segment.
6. **No overlapping positions:** a new signal is not accepted on the same candle in which the prior trade exits; the next eligible signal must occur after the exit candle.
7. **Cost units:** optional cost inputs are total round-trip XAUUSD price units per trade. No default cost is inserted. Without an explicit cost input, only gross/pre-cost results are available and net metrics remain unavailable.

No final-test evaluation is authorized by this clarification. The final 20% remains sealed until candidate, data fingerprint, and cost assumptions are frozen and explicitly authorized.
