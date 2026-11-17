from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from analysis_engine import analyse_timeframes
from market_data import MarketDataError, get_market_candles
import json


app = FastAPI(
    title="Gold AI",
    description="Gold Trading Analysis API",
    version="1.3.0"
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
    selected_timeframes = ["M1", "M5", "M15", "M30", "H1", "H4"]
    market_data = {}
    provider_errors = {}

    # Fetch all timeframes concurrently so one slow request does not delay
    # the other five unnecessarily.
    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs = {
            executor.submit(get_market_candles, timeframe): timeframe
            for timeframe in selected_timeframes
        }
        for job in as_completed(jobs):
            timeframe = jobs[job]
            try:
                market_data[timeframe] = job.result()
            except Exception as exc:
                provider_errors[timeframe] = str(exc)

    analysis = analyse_timeframes(market_data)
    if provider_errors:
        error_summary = "; ".join(
            f"{timeframe}: {message}"
            for timeframe, message in sorted(provider_errors.items())
        )
        analysis["analysis_status"] = "data_not_ready"
        analysis["research_signal"] = "WAIT"
        analysis["technical_bias"] = "NEUTRAL"
        analysis["message"] += " Provider errors: " + error_summary

    message = analysis["message"]
    if analysis["research_signal"] in {"BUY", "SELL"}:
        message += (
            " Gold AI still displays WAIT as its trade signal because this is "
            "a reference-market feed, not your MT5 broker's execution feed."
        )
    else:
        message += (
            " The current feed is reference-market data, not your MT5 broker's "
            "execution feed."
        )

    return {
        "symbol": "XAUUSD",
        "signal": "WAIT",
        "ai_trained": False,
        "execution_ready": False,
        "research_only": True,
        "data_source": "XAUS reference-market feed",
        **analysis,
        "message": message
    }


@app.get("/market/spot")
def gold_spot():
    url = "https://xaus.com/api/v1/spot?compact=1"
    try:
        with urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        price = data.get("spot_usd_oz")
        if price is None:
            raise HTTPException(
                status_code=502,
                detail="Gold price unavailable"
            )

        return {
            "symbol": "XAUUSD",
            "price": price,
            "currency": "USD",
            "unit": "troy ounce",
            "updated_at": data.get("updated_at"),
            "price_as_of": data.get("price_as_of"),
            "data_state": data.get("data_state"),
            "source": "XAUS"
        }

    except HTTPException:
        raise
    except (URLError, HTTPError, TimeoutError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve Gold market data"
        )


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
        return get_market_candles(selected_timeframe)
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
        "build": "GOLD-AI-CANDLES-140",
        "version": app.version,
        "file": __file__,
        "routes": [route.path for route in app.routes]
    }
