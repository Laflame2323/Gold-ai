
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
import json


app = FastAPI(
    title="Gold AI",
    description="Gold Trading Analysis API",
    version="1.2.0"
)


# Allow the website to communicate with the backend
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
    return {
        "symbol": "XAUUSD",
        "signal": "WAIT",
        "message": "Waiting for reliable market data and technical analysis.",
        "ai_trained": False
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


@app.post("/assistant")
def assistant(payload: AssistantRequest):
    prompt = payload.prompt.strip().lower()

    if not prompt:
        return {
            "response": "Please enter a message."
        }

    # Check trading execution requests
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

    # Check gold market analysis requests
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
                    "BUY or SELL signal. We still need broker candle "
                    "data and technical analysis across our six timeframes."
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
    # Gold AI assistant endpoint update



