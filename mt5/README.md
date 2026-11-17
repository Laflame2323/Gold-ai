# Gold AI — MT5 Read-Only Bridge

The `GoldAI_ReadOnly_Bridge.mq5` Expert Advisor sends **completed XAUUSD candles only** to Gold AI. It does not place, modify, or close trades. It does not request account passwords, account numbers, or trading permissions.

## Before using it

1. Gold AI's backend must have the private Render environment variable `MT5_INGEST_TOKEN` configured.
2. Generate a random secret of at least 32 bytes. Add it only to Render's environment variable `MT5_INGEST_TOKEN`, then enter the same value locally in the EA input `IngestToken`. Never send it in chat, screenshots, or GitHub.
3. In desktop MT5, open **Tools → Options → Expert Advisors** and enable **Allow WebRequest for listed URL**. Add:
   `https://gold-ai-backend-p9el.onrender.com`
4. Open **File → Open Data Folder → MQL5 → Experts** and copy `GoldAI_ReadOnly_Bridge.mq5` there.
5. Open MetaEditor, compile the EA, and return to MT5.
6. Attach the EA to your broker's gold chart (for example `XAUUSD`, `XAUUSDm`, or `GOLD`). It uses the chart's exact symbol automatically.
7. Keep the terminal or MT5 VPS running. Check the Experts tab for successful uploads.

## What it sends

- Six completed timeframes: M1, M5, M15, M30, H1 and H4.
- Up to 5,000 historical closed bars per timeframe (default 5,000) on first connection, archived in safe 500-row database batches.
- After the initial history upload, only the latest 100 completed bars are refreshed when a new bar appears, keeping the archive current without repeatedly uploading the full history.
- One timeframe is processed per timer tick to avoid blocking MT5 with six large requests at once.
- Broker server label, broker symbol, OHLC, tick volume, real volume, and spread points.
- Broker-server timestamps converted to UTC using the current server/GMT offset. The offset used is recorded with each batch.

The backend validates the token, symbol, timeframe, OHLC values, timestamp offset, and candle completion time before archiving. Broker candles are stored under a separate source label from the XAUS reference feed. Once verified broker candles are available, Gold AI automatically uses that single broker/symbol feed for chart candles and multi-timeframe analysis instead of mixing it with XAUS reference data. MT5 does not provide a historical table of broker UTC-offset changes, so bars spanning a broker daylight-saving transition may need timestamp correction before cross-source research.

## Important

- MT5 mobile apps cannot run Expert Advisors. A Windows/Mac desktop MT5 terminal or an MT5 VPS is required.
- The bridge is read-only. It contains no order-placement code.
- A successful upload confirms ingestion, not prediction accuracy or trading readiness.
- Demo order execution will require a separate demo-only adapter, risk limits, spread checks, stop-loss validation, and an emergency kill switch. Real-money execution remains disabled.
