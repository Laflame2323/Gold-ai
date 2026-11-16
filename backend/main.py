
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

