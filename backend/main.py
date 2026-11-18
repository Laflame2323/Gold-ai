from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.request import Request
from analysis_engine import analyse_timeframes
from market_data import MarketDataError, _fetch_json_with_retries, get_market_candles, get_daily_history, get_intraday_prices
from market_storage import archive_market_candles, archive_daily_history, archive_intraday_prices, archive_gold_cot, archive_macro_context, record_collector_run, get_latest_mt5_source, get_mt5_market_candles, MarketStorageError
from cot_data import COTDataError, get_gold_cot
from macro_data import MacroDataError, get_macro_context
import json
import hmac
import math
import os
import logging
import time
from mt5_ingest import MT5Batch, archive_mt5_batch


app = FastAPI(
    title="Gold AI",
    description="Gold Trading Analysis API",
    version="1.3.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AssistantRequest(BaseModel):
    prompt: str


@app.get("/")
def home():
    return {
        "status": "online",
        "name": "Gold AI",
        "message": "Gold AI backend is running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/analyse")
def analyse():
    started_at = datetime.now(timezone.utc)
    selected_timeframes = ["M1", "M5", "M15", "M30", "H1", "H4"]
    market_data = {}
    archive_results = {}
    provider_errors = {}
    mt5_source = None

    # Prefer one broker's own feed when it is present. Never mix MT5 and XAUS
    # candles in the same analysis.
    try:
        mt5_source = get_latest_mt5_source()
    except MarketStorageError as exc:
        provider_errors["MT5 archive"] = str(exc)[:300]

    if mt5_source:
        for timeframe in selected_timeframes:
            try:
                market_data[timeframe] = get_mt5_market_candles(
                    mt5_source["symbol"], mt5_source["source"], timeframe
                )
            except Exception as exc:
                provider_errors[timeframe] = str(exc)[:300]
        history_archive = {}
        collector_audit = {"status": "already_archived", "source": mt5_source["source"]}
        data_source = "Authenticated MT5 broker feed (read-only)"
        response_symbol = mt5_source["symbol"]
    else:
        # Reference feed is used only when no broker feed has been archived.
        with ThreadPoolExecutor(max_workers=6) as executor:
            jobs = {
                executor.submit(get_market_candles, timeframe): timeframe
                for timeframe in selected_timeframes
            }
            for job in as_completed(jobs):
                timeframe = jobs[job]
                try:
                    market_data[timeframe] = job.result()
                    archive_results[timeframe] = archive_market_candles(market_data[timeframe])
                except Exception as exc:
                    provider_errors[timeframe] = str(exc)[:300]

        history_archive = {}
        try:
            daily_history = get_daily_history()
            history_archive["daily"] = archive_daily_history(daily_history)
        except Exception as exc:
            history_archive["daily"] = {"status": "error", "message": str(exc)[:250]}

        try:
            intraday_history = get_intraday_prices(hours=48)
            history_archive["intraday"] = archive_intraday_prices(intraday_history)
        except Exception as exc:
            history_archive["intraday"] = {"status": "error", "message": str(exc)[:250]}

        collector_audit = record_collector_run(started_at, archive_results, provider_errors)
        data_source = "XAUS reference-market feed"
        response_symbol = "XAUUSD"

    analysis = analyse_timeframes(market_data)
    if provider_errors:
        error_summary = "; ".join(
            f"{timeframe}: {message}"
            for timeframe, message in sorted(provider_errors.items())
        )
        analysis["analysis_status"] = "data_not_ready"
        analysis["research_signal"] = "WAIT"
        analysis["technical_bias"] = "NEUTRAL"
        analysis["alignment_score"] = 0
        analysis["message"] += " Data errors: " + error_summary

    if mt5_source:
        message = analysis["message"] + (
            " These are authenticated broker candles, but Gold AI remains research-only; "
            "demo execution is not connected or enabled."
        )
    else:
        message = analysis["message"] + (
            " The current feed is XAUS reference-market data, not your MT5 broker's "
            "execution feed. Connect the read-only MT5 bridge for broker-specific analysis."
        )

    return {
        "symbol": response_symbol,
        "signal": "WAIT",
        "ai_trained": False,
        "execution_ready": False,
        "research_only": True,
        "data_source": data_source,
        "archive_status": archive_results,
        "history_archive": history_archive,
        "collector_audit": collector_audit,
        **analysis,
        "message": message
    }


@app.get("/research/backtest")
def research_backtest(timeframe: str = "H1", horizon: int = 5):
    """Run a historical directional test on one consistent gold candle source."""
    from research_backtest import run_directional_backtest

    selected_timeframe = timeframe.upper()
    supported = {"M1", "M5", "M15", "M30", "H1", "H4"}
    if selected_timeframe not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4.",
        )
    if horizon < 1 or horizon > 100:
        raise HTTPException(status_code=400, detail="horizon must be between 1 and 100 candles.")

    try:
        mt5_source = get_latest_mt5_source()
        if mt5_source:
            market = get_mt5_market_candles(
                mt5_source["symbol"], mt5_source["source"], selected_timeframe
            )
            source_label = "Authenticated MT5 broker archive (read-only)"
            symbol = mt5_source["symbol"]
            broker_source = mt5_source["source"]
        else:
            market = get_market_candles(selected_timeframe)
            source_label = "XAUS reference-market archive (not broker execution prices)"
            symbol = market.get("symbol", "XAUUSD")
            broker_source = None

        result = run_directional_backtest(market.get("candles") or [], horizon=horizon)
        return {
            **result,
            "symbol": symbol,
            "timeframe": selected_timeframe,
            "data_source": source_label,
            "broker_source": broker_source,
            "model_type": "rule_based_research_baseline",
            "ai_trained": False,
            "accuracy_is_live": False,
            "read_only": True,
            "execution_enabled": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MarketStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/research/backtest/compare")
def research_backtest_compare(timeframe: str = "H1"):
    """Compare the same directional strategy across fixed candle horizons."""
    from research_backtest import compare_directional_horizons

    selected_timeframe = timeframe.upper()
    supported = {"M1", "M5", "M15", "M30", "H1", "H4"}
    if selected_timeframe not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4.",
        )
    try:
        mt5_source = get_latest_mt5_source()
        if mt5_source:
            market = get_mt5_market_candles(
                mt5_source["symbol"], mt5_source["source"], selected_timeframe
            )
            source_label = "Authenticated MT5 broker archive (read-only)"
            symbol = mt5_source["symbol"]
            broker_source = mt5_source["source"]
        else:
            market = get_market_candles(selected_timeframe)
            source_label = "XAUS reference-market feed (not broker execution prices)"
            symbol = market.get("symbol", "XAUUSD")
            broker_source = None

        result = compare_directional_horizons(market.get("candles") or [])
        return {
            **result,
            "symbol": symbol,
            "timeframe": selected_timeframe,
            "data_source": source_label,
            "broker_source": broker_source,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MarketStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/research/backtest/holdout")
def research_backtest_holdout(
    timeframe: str = "H1",
    horizon: int = 5,
    holdout_fraction: float = 0.25,
):
    """Evaluate the fixed research rule on a later chronological holdout."""
    from research_backtest import chronological_holdout_backtest

    selected_timeframe = timeframe.upper()
    supported = {"M1", "M5", "M15", "M30", "H1", "H4"}
    if selected_timeframe not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4.",
        )
    if horizon < 1 or horizon > 100:
        raise HTTPException(status_code=400, detail="horizon must be between 1 and 100 candles.")
    if not 0.1 <= holdout_fraction <= 0.5:
        raise HTTPException(status_code=400, detail="holdout_fraction must be between 0.1 and 0.5.")

    try:
        mt5_source = get_latest_mt5_source()
        if mt5_source:
            market = get_mt5_market_candles(
                mt5_source["symbol"], mt5_source["source"], selected_timeframe
            )
            source_label = "Authenticated MT5 broker archive (read-only)"
            symbol = mt5_source["symbol"]
            broker_source = mt5_source["source"]
        else:
            market = get_market_candles(selected_timeframe)
            source_label = "XAUS reference-market feed (not broker execution prices)"
            symbol = market.get("symbol", "XAUUSD")
            broker_source = None

        result = chronological_holdout_backtest(
            market.get("candles") or [],
            horizon=horizon,
            holdout_fraction=holdout_fraction,
        )
        return {
            **result,
            "symbol": symbol,
            "timeframe": selected_timeframe,
            "data_source": source_label,
            "broker_source": broker_source,
            "model_type": "rule_based_research_baseline",
            "ai_trained": False,
            "accuracy_is_live": False,
            "read_only": True,
            "execution_enabled": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MarketStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/research/ml/evaluate")
def research_ml_evaluate(timeframe: str = "H1", horizon: int = 5, min_move_pct: float = 0.0):
    """Train an ephemeral research candidate and score a later chronological test block."""
    from research_ml import evaluate_logistic_research

    selected_timeframe = timeframe.upper()
    supported = {"M1", "M5", "M15", "M30", "H1", "H4"}
    if selected_timeframe not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4.",
        )
    if horizon < 1 or horizon > 100:
        raise HTTPException(status_code=400, detail="horizon must be between 1 and 100 candles.")

    request_started = time.perf_counter()
    logger = logging.getLogger("gold_ai.research_ml")
    logger.info(
        "RESEARCH_EVAL_START timeframe=%s horizon=%s min_move_pct=%s",
        selected_timeframe, horizon, min_move_pct,
    )
    try:
        stage_started = time.perf_counter()
        mt5_source = get_latest_mt5_source()
        logger.info(
            "RESEARCH_EVAL_SOURCE_LOOKUP_DONE elapsed_ms=%.1f mt5_source_found=%s",
            (time.perf_counter() - stage_started) * 1000, bool(mt5_source),
        )

        stage_started = time.perf_counter()
        if mt5_source:
            market = get_mt5_market_candles(
                mt5_source["symbol"], mt5_source["source"], selected_timeframe
            )
            source_label = "Authenticated MT5 broker archive (read-only)"
            symbol = mt5_source["symbol"]
            broker_source = mt5_source["source"]
        else:
            market = get_market_candles(selected_timeframe)
            source_label = "XAUS reference-market feed (not broker execution prices)"
            symbol = market.get("symbol", "XAUUSD")
            broker_source = None
        candles = market.get("candles") or []
        logger.info(
            "RESEARCH_EVAL_CANDLE_FETCH_DONE elapsed_ms=%.1f candle_count=%s source=%s",
            (time.perf_counter() - stage_started) * 1000, len(candles), source_label,
        )

        stage_started = time.perf_counter()
        result = evaluate_logistic_research(
            candles, horizon=horizon, min_move_pct=min_move_pct
        )
        logger.info(
            "RESEARCH_EVAL_MODEL_DONE elapsed_ms=%.1f total_elapsed_ms=%.1f status=%s",
            (time.perf_counter() - stage_started) * 1000,
            (time.perf_counter() - request_started) * 1000,
            result.get("status"),
        )
        return {
            **result,
            "symbol": symbol,
            "timeframe": selected_timeframe,
            "data_source": source_label,
            "broker_source": broker_source,
            "accuracy_is_live": False,
            "research_only": True,
            "read_only": True,
            "execution_enabled": False,
        }
    except ValueError as exc:
        logger.warning(
            "RESEARCH_EVAL_VALIDATION_ERROR elapsed_ms=%.1f error=%s",
            (time.perf_counter() - request_started) * 1000, exc,
        )
        raise HTTPException(status_code=422, detail=str(exc))
    except MarketStorageError as exc:
        logger.exception(
            "RESEARCH_EVAL_STORAGE_ERROR elapsed_ms=%.1f",
            (time.perf_counter() - request_started) * 1000,
        )
        raise HTTPException(status_code=503, detail=str(exc))
    except MarketDataError as exc:
        logger.exception(
            "RESEARCH_EVAL_MARKET_ERROR elapsed_ms=%.1f",
            (time.perf_counter() - request_started) * 1000,
        )
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        logger.exception(
            "RESEARCH_EVAL_UNEXPECTED_ERROR elapsed_ms=%.1f",
            (time.perf_counter() - request_started) * 1000,
        )
        raise


@app.get("/research/cot")
def gold_cot():
    """Return delayed official CFTC gold positioning and archive its weekly history."""
    try:
        payload = get_gold_cot()
    except COTDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    payload["archive"] = archive_gold_cot(payload)
    return payload


@app.post("/broker/mt5/candles")
def ingest_mt5_candles(
    payload: MT5Batch,
    x_mt5_token: str | None = Header(default=None, alias="X-MT5-Token"),
):
    """Accept authenticated, read-only, completed MT5 candles."""
    expected_token = os.getenv("MT5_INGEST_TOKEN", "")
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="MT5 ingestion is locked until MT5_INGEST_TOKEN is configured.",
        )
    if not x_mt5_token or not hmac.compare_digest(expected_token, x_mt5_token):
        raise HTTPException(status_code=401, detail="Invalid MT5 ingestion token.")
    try:
        result = archive_mt5_batch(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result.get("status") != "saved":
        raise HTTPException(status_code=503, detail="Broker candle archive is unavailable.")
    return {
        "status": "saved",
        "rows_sent": result.get("rows_sent", 0),
        "symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "broker_server": payload.broker_server,
        "read_only": True,
    }


@app.get("/broker/mt5/status")
def mt5_status():
    """Expose safe connection status without revealing the ingestion secret."""
    configured = bool(os.getenv("MT5_INGEST_TOKEN"))
    try:
        source = get_latest_mt5_source()
    except MarketStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "ingestion_configured": configured,
        "ingestion_locked": not configured,
        "broker_feed_available": bool(source),
        "symbol": source.get("symbol") if source else None,
        "last_received_at": source.get("fetched_at") if source else None,
        "read_only": True,
        "execution_enabled": False,
    }


@app.get("/research/macro")
def macro_context():
    """Return public FRED macro context and archive its daily observations."""
    try:
        payload = get_macro_context()
    except MacroDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    payload["archive"] = archive_macro_context(payload)
    return payload



@app.get("/market/spot")
def gold_spot():
    request = Request(
        "https://xaus.com/api/v1/spot?compact=1",
        headers={"Accept": "application/json", "User-Agent": "GoldAI/1.0"},
    )
    try:
        data = _fetch_json_with_retries(
            request,
            "Could not retrieve Gold market data after retrying transient failures.",
            attempts=3,
            timeout=15,
        )
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="Gold price response was invalid.")

        price = data.get("spot_usd_oz")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise HTTPException(status_code=502, detail="Gold price unavailable")
        if not math.isfinite(float(price)) or float(price) <= 0:
            raise HTTPException(status_code=502, detail="Gold price response was invalid.")

        return {
            "symbol": "XAUUSD",
            "price": float(price),
            "currency": "USD",
            "unit": "troy ounce",
            "updated_at": data.get("updated_at"),
            "price_as_of": data.get("price_as_of"),
            "data_state": data.get("data_state"),
            "source": "XAUS"
        }
    except HTTPException:
        raise
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/market/candles")
def market_candles(timeframe: str = "M15"):
    selected_timeframe = timeframe.upper()
    supported = {"M1", "M5", "M15", "M30", "H1", "H4"}

    if selected_timeframe not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4."
        )

    try:
        mt5_source = get_latest_mt5_source()
        if mt5_source:
            market = get_mt5_market_candles(
                mt5_source["symbol"], mt5_source["source"], selected_timeframe
            )
            if not market["candles"]:
                raise HTTPException(
                    status_code=503,
                    detail=f"No verified MT5 {selected_timeframe} candles are archived yet.",
                )
            market["archive"] = {"status": "already_archived", "rows_sent": 0}
            return market

        market = get_market_candles(selected_timeframe)
        market["archive"] = archive_market_candles(market)
        return market
    except MarketStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/market/archive-test")
def market_archive_test(timeframe: str = "M1"):
    selected_timeframe = timeframe.upper()
    supported = {"M1", "M5", "M15", "M30", "H1", "H4"}
    if selected_timeframe not in supported:
        raise HTTPException(
            status_code=400,
            detail="Unsupported timeframe. Use M1, M5, M15, M30, H1 or H4."
        )
    try:
        market = get_market_candles(selected_timeframe)
        archive = archive_market_candles(market)
        return {
            "symbol": market.get("symbol", "XAUUSD"),
            "timeframe": selected_timeframe,
            "market_data": "available",
            "archive_status": archive.get("status"),
            "rows_sent": archive.get("rows_sent", 0),
            "http_status": archive.get("http_status"),
            "message": archive.get("message"),
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/assistant")
def assistant(payload: AssistantRequest):
    prompt = payload.prompt.strip().lower()

    if not prompt:
        return {"response": "Please enter a message."}

    if any(word in prompt for word in [
        "execute",
        "open trade",
        "buy",
        "sell",
        "close trade",
        "place trade"
    ]):
        return {
            "response": (
                "Trade execution is not connected yet. "
                "No trade has been placed. "
                "MT5 integration and testing are still required."
            )
        }

    if any(word in prompt for word in [
        "analyse",
        "analyze",
        "market",
        "gold price",
        "price of gold"
    ]):
        try:
            market = gold_spot()
            price = float(market["price"])
            data_state = market.get("data_state") or {}
            status = data_state.get("status", "unknown")

            return {
                "response": (
                    f"The latest indicative XAU/USD spot price is "
                    f"${price:,.2f} per troy ounce. "
                    f"Data status: {status}. "
                    "This spot price alone cannot generate a reliable "
                    "BUY or SELL signal. Broker candle data and "
                    "technical analysis are still needed."
                )
            }

        except Exception:
            return {
                "response": (
                    "I cannot retrieve the gold price right now. "
                    "Please try again later."
                )
            }

    return {
        "response": (
            "Hello! I am Gold AI. You can ask me to analyse gold, "
            "check the gold price, or explain trading concepts. "
            "Advanced AI analysis and MT5 integration are still being developed."
        )
    }


@app.get("/debug/build")
def debug_build():
    return {
        "build": "GOLD-AI-COLLECTOR-AUDIT-131",
        "version": app.version,
        "file": __file__,
        "routes": [route.path for route in app.routes]
    }
