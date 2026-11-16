
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
import json

app = FastAPI(
    title="Gold AI",
    description="Gold Trading Analysis API",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        "message": "Waiting for market analysis.",
        "ai_trained": False
    }

@app.get("/market/spot")
def gold_spot():
    url = "https://xaus.com/api/v1/spot?compact=1"

    try:
        with urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        if not data.get("spot_usd_oz"):
            raise HTTPException(
                status_code=502,
                detail="Gold price unavailable"
            )

        return {
            "symbol": "XAUUSD",
            "price": data["spot_usd_oz"],
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
        # Gold AI live market integration

@app.post("/assistant")
def assistant(payload: dict):
    prompt = str(payload.get("prompt", "")).strip().lower()

    if not prompt:
        return {"response": "Please enter a message."}

    if any(word in prompt for word in ["analyse", "analyze", "market", "gold price"]):
        try:
            market = gold_spot()
            price = market["price"]
            status = market.get("data_state", {}).get("status", "unknown")

            return {
                "response": (
                    f"The latest indicative XAU/USD spot price is "
                    f"${price:,.2f} per troy ounce. "
                    f"Data status: {status}. "
                    "This price alone is not enough to generate a reliable "
                    "BUY or SELL signal. Candle data and technical analysis "
                    "are still being developed."
                )
            }

        except Exception:
            return {
                "response": "I cannot retrieve the gold price right now. Please try again."
            }

    if any(word in prompt for word in ["execute", "open trade", "buy", "sell", "close trade"]):
        return {
            "response": (
                "Trade execution is not connected yet. "
                "No trade has been placed. We still need to integrate and test MT5."
            )
        }

    return {
        "response": (
            "I am your Gold AI assistant. You can ask me to analyse gold, "
            "check its price, or explain trading concepts. "
            "Advanced market analysis is still being developed."
        )
    }


