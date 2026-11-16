
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Gold AI",
    description="Gold Trading Analysis API",
    version="1.0.0"
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
    return {
        "status": "healthy"
    }

@app.get("/analyse")
def analyse():
    return {
        "symbol": "XAUUSD",
        "signal": "WAIT",
        "message": "Waiting for live market data.",
        "ai_trained": False
    }
