# Gold AI — MT5 Read-Only Bridge

This optional MetaTrader 5 Expert Advisor sends **completed XAUUSD candles only** to Gold AI. It does not place, modify, or close trades. It does not request account passwords, account numbers, or trading permissions.

## Before using it

1. Gold AI's backend must have the private Render environment variable `MT5_INGEST_TOKEN` configured.
2. Put the same token into the EA input `IngestToken`.
3. Set `GoldSymbol` to your broker's exact gold symbol (for example `XAUUSD`, `XAUUSDm`, or `GOLD`).
4. In desktop MT5, open **Tools → Options → Expert Advisors** and enable **Allow WebRequest for listed URL**. Add:
   `https://gold-ai-backend-p9el.onrender.com`
5. Attach the EA to a chart, enable Algo Trading (this EA does not trade), and keep the terminal or VPS running.

## What it sends

- Six completed timeframes: M1, M5, M15, M30, H1, H4.
- Up to 500 historical closed bars per timeframe on first connection.
- Subsequent newly completed bars, including any bars missed while the terminal was offline.
- Broker server label, broker symbol, OHLC, tick volume, real volume, and spread points.

The backend validates the token, symbol, timeframe, OHLC values, and candle completion time before archiving. Broker candles are stored under a separate source label from the XAUS reference feed.

## Important

- MT5 mobile apps cannot run Expert Advisors. A Windows/Mac desktop MT5 terminal or an MT5 VPS is required.
- Keep the token private. Never paste it into public GitHub files or screenshots.
- The bridge is read-only. Live trading remains disabled in Gold AI.
- A broker's historical data availability varies. The initial upload may contain fewer than 500 candles.
