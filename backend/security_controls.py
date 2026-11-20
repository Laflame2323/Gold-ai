"""Baseline API hardening for Gold AI.

The in-process rate limiter is a defence-in-depth guard, not a substitute for
edge/WAF limits. Use a shared limiter (for example Redis/Upstash) before scaling
to multiple Render instances.
"""
from collections import defaultdict, deque
import json
import time
from typing import Deque


class SecurityHeadersRateLimitMiddleware:
    def __init__(
        self,
        app,
        requests_per_minute: int = 120,
        writes_per_minute: int = 30,
        window_seconds: int = 60,
        max_clients: int = 10000,
    ):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.writes_per_minute = writes_per_minute
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.hits: dict[str, Deque[float]] = defaultdict(deque)

    @staticmethod
    def _security_headers(path: str) -> dict[bytes, bytes]:
        headers = {
            b"x-content-type-options": b"nosniff",
            b"x-frame-options": b"DENY",
            b"referrer-policy": b"no-referrer",
            b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
            b"strict-transport-security": b"max-age=31536000; includeSubDomains",
        }
        if path.startswith("/research/") or path.startswith("/broker/"):
            headers[b"cache-control"] = b"no-store"
        return headers

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()
        client = scope.get("client")
        # Use the ASGI peer address. Never trust arbitrary X-Forwarded-For
        # headers supplied by callers; configure trusted proxy handling at host.
        client_ip = client[0] if client else "unknown"
        is_write = method in {"POST", "PUT", "PATCH", "DELETE"}
        bucket = f"{client_ip}:{'write' if is_write else 'read'}"
        limit = self.writes_per_minute if is_write else self.requests_per_minute

        exempt = path in {"/", "/health"}
        now = time.monotonic()
        if not exempt:
            # Bound memory under high-cardinality client traffic.
            if len(self.hits) >= self.max_clients and bucket not in self.hits:
                self._prune(now, force=True)
                if len(self.hits) >= self.max_clients:
                    await self._reject(send, path, "Rate limiter is at capacity. Try again shortly.")
                    return
            events = self.hits[bucket]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                await self._reject(send, path, "Rate limit exceeded. Try again shortly.")
                return
            events.append(now)

        async def hardened_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                for key, value in self._security_headers(path).items():
                    if key not in existing:
                        headers.append((key, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, hardened_send)

    async def _reject(self, send, path: str, detail: str):
        body = json.dumps({"detail": detail}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(self.window_seconds).encode()),
        ]
        headers.extend(self._security_headers(path).items())
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _prune(self, now: float, force: bool = False):
        cutoff = now - self.window_seconds
        for key in list(self.hits):
            events = self.hits[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                self.hits.pop(key, None)
            if force and len(self.hits) < self.max_clients * 3 // 4:
                break
