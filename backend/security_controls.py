"""Baseline API hardening and owner-only authentication for Gold AI.

The in-process rate limiter is a defence-in-depth guard, not a substitute for
edge/WAF limits. Use a shared limiter before scaling to multiple Render instances.
"""
from collections import defaultdict, deque
import asyncio
import json
import os
import time
from typing import Deque
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class OwnerAuthMiddleware:
    """Require a valid Supabase session belonging to the configured owner."""

    PUBLIC_PATHS = {"/", "/health", "/research/public/evaluate-profit-aware-triple-barrier-mtf", "/broker/mt5/candles", "/broker/mt5/ticks"}

    def __init__(self, app, owner_user_id=None, supabase_url=None, api_key=None):
        self.app = app
        self.owner_user_id = owner_user_id or os.getenv("GOLD_AI_OWNER_USER_ID", "")
        self.supabase_url = (supabase_url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        # Auth user lookup only needs a public project API key. Never fall
        # back to a secret/service-role key for end-user session validation.
        self.api_key = (
            api_key
            or os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        )

    def _verify_owner(self, token: str) -> bool:
        if not self.owner_user_id or not self.supabase_url or not self.api_key:
            raise RuntimeError("Owner authentication is not configured.")
        request = Request(
            f"{self.supabase_url}/auth/v1/user",
            headers={
                "apikey": self.api_key,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                user = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                return False
            raise
        return isinstance(user, dict) and user.get("id") == self.owner_user_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()
        # CORS preflight has no user session. The MT5 ingestion routes retain
        # their independent X-MT5-Token check inside the route handlers.
        if method == "OPTIONS" or path in self.PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        raw_headers = dict(scope.get("headers", []))
        authorization = raw_headers.get(b"authorization", b"").decode("latin-1").strip()
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await self._reject(send, 401, "A valid owner login is required.")
            return

        try:
            allowed = await asyncio.to_thread(self._verify_owner, token.strip())
        except Exception:
            await self._reject(send, 503, "Owner authentication is temporarily unavailable.")
            return

        if not allowed:
            await self._reject(send, 403, "This Gold AI account is not authorised.")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, detail: str):
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
            ],
        })
        await send({"type": "http.response.body", "body": body})


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
        client_ip = client[0] if client else "unknown"
        is_write = method in {"POST", "PUT", "PATCH", "DELETE"}
        bucket = f"{client_ip}:{'write' if is_write else 'read'}"
        limit = self.writes_per_minute if is_write else self.requests_per_minute

        exempt = path in {"/", "/health"}
        now = time.monotonic()
        if not exempt:
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
