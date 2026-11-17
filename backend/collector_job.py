"""Scheduled collector for Gold AI.

Calls the backend's existing read-only analysis endpoint. The backend performs
market retrieval and writes candles to Supabase using its own private secret.
This job intentionally contains no Supabase credentials.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get(
    "GOLD_AI_API_URL",
    "https://gold-ai-backend-p9el.onrender.com",
).rstrip("/")
URL = f"{BASE_URL}/analyse"
REQUIRED = {"M1", "M5", "M15", "M30", "H1", "H4"}


def main() -> int:
    request = Request(URL, headers={"Accept": "application/json", "User-Agent": "GoldAI-Collector/1.0"})
    try:
        with urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except HTTPError as exc:
        print(f"Collector failed: backend HTTP {exc.code}: {exc.read(500).decode('utf-8', errors='replace')}")
        return 1
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"Collector failed: {type(exc).__name__}: {exc}")
        return 1

    archives = payload.get("archive_status") or {}
    saved = sorted(tf for tf, result in archives.items() if result.get("status") == "saved")
    failed = {
        tf: result.get("status", "missing")
        for tf, result in archives.items()
        if result.get("status") != "saved"
    }
    missing = sorted(REQUIRED - set(archives))
    print(json.dumps({
        "http_status": status,
        "symbol": payload.get("symbol", "XAUUSD"),
        "saved_timeframes": saved,
        "failed_timeframes": failed,
        "missing_timeframes": missing,
        "ai_trained": payload.get("ai_trained", False),
        "research_only": payload.get("research_only", True),
    }, sort_keys=True))

    return 0 if not failed and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
