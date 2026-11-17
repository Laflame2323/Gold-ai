# Gold AI

Gold AI is a research-first XAUUSD market-monitoring application. It collects reference-market candles and macro/positioning context, calculates conservative multi-timeframe technical indicators, and archives market observations for later research.

## Current application

- Frontend: Vercel production deployment: https://gold-ai-frontend-tawny.vercel.app
- Backend: Render service: https://gold-ai-backend-p9el.onrender.com
- Database: Supabase project used for private market-data archives.
- Instrument: Gold / XAUUSD.
- Reference feed: XAUS spot and candle APIs. This is not the user's broker quote or execution feed.

## Current capabilities

- Spot gold price endpoint with retry handling and response validation.
- Closed-candle data for M1, M5, M15, M30, H1 and derived H4.
- Candle validation, freshness checks, and duplicate archive-write suppression.
- Multi-timeframe technical analysis with a conservative WAIT default.
- Daily history and sampled intraday price archives.
- FRED macro context and official CFTC gold positioning context.
- Collector-run audit records.
- Authenticated, read-only MT5 candle ingestion with broker timestamp conversion.
- Safe MT5 status endpoint at /broker/mt5/status; it reports configuration and feed presence without exposing the secret.
- When verified MT5 data exists, the analysis and chart endpoints select that one broker/symbol feed and never mix it with XAUS reference candles.
- MT5 Expert Advisor source in mt5/GoldAI_ReadOnly_Bridge.mq5.

## Backend setup

From the repository root:

    cd backend
    python -m pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000

Run backend unit tests:

    cd backend
    python -m unittest discover -s . -p "test_*.py" -v

## Backend environment variables

Configure these in the hosting provider's private environment settings, never in frontend code or committed files:

- SUPABASE_URL — Supabase project URL.
- SUPABASE_SECRET_KEY — private Supabase secret/service key. The backend also supports the legacy SUPABASE_SERVICE_ROLE_KEY name.
- MT5_INGEST_TOKEN — a newly generated random secret used only by the authenticated MT5 ingestion endpoint.

Do not publish, commit, screenshot, or paste secret values into chat.

## Connecting MT5

Read the MT5 bridge setup guide at mt5/README.md. MT5 Expert Advisors require a desktop MT5 terminal or MT5 VPS; the mobile app cannot run the bridge. The bridge uploads completed candles only and does not place orders.

The broker UTC offset is required. The backend converts broker-server candle times to UTC before archiving. Historical daylight-saving offset changes are not automatically reconstructed, so older bars crossing a broker DST transition require special review. Until verified broker candles are uploaded, Gold AI continues to use the XAUS reference feed and labels it as such.

## Research and trading status

- The current /analyse response is research-only.
- ai_trained is false and execution_ready is false.
- The public XAUS reference feed must not be treated as broker execution data.
- Existing historical benchmark results did not demonstrate a reliable or profitable signal. Do not use the current technical score as a production trading strategy.
- No live order execution is enabled.
- Demo execution is a separate future milestone and must remain demo-account-only, with broker-feed verification, walk-forward validation, spread/slippage modelling, strict position and loss limits, mandatory stop-losses, and a kill switch.

## Data and security principles

- Never use future target/label columns as model input features.
- Keep raw market archives and research labels separate.
- Keep Supabase private tables protected by RLS and service-role-only access.
- Reject invalid, incomplete, future, or unauthenticated broker candle uploads.
- Never fabricate missing market data or claim a model is trained without completed training and validation.
