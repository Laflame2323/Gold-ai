# Gold AI research training job

This is an isolated, read-only research worker. It does not place, modify, or close trades.

## What it does

- Reads only verified candles from one authenticated MT5 broker source in Supabase.
- Requires recent H4, H1, M30 and M15 archives; if any timeframe is stale, the run stops.
- Trains the existing ATR triple-barrier meta-label candidate on M30 with H4/H1/M30/M15 context.
- Stores metrics, source/freshness details, and the compressed candidate artifact in `public.research_training_runs`.
- Keeps candidate promotion manual. It never loads a candidate into the production signal path.

The candidate's historical split metrics are not a live forward result. The evaluator does not include spread, commission, slippage or swap costs. Live tick replay remains a separate validation step once the MT5 tick collector is active.

## Run manually

From the `backend` directory, with the same private Supabase environment variables used by the research API:

```bash
python research_training_job.py
```

Required environment variables:
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY` (or the existing `SUPABASE_SERVICE_ROLE_KEY` fallback)

## Scheduling

Intended cadence: every 6 hours, after fresh completed broker candles have been archived. The scheduler has not been provisioned or enabled yet. Do not create a paid Render Cron Job without confirming its price and the user's approval. The existing Render web service deploys a different research branch, so this worker must be deployed explicitly and separately.
