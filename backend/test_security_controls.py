import unittest
from security_controls import SecurityHeadersRateLimitMiddleware


async def _asgi_request(middleware, path="/research/status", method="GET", client=("127.0.0.1", 12345)):
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": [],
        "client": client,
        "server": ("test", 80),
        "scheme": "http",
    }
    middleware.app = app
    await middleware(scope, receive, send)
    return messages


class SecurityControlsTests(unittest.IsolatedAsyncioTestCase):
    def test_rate_limit_configuration(self):
        middleware = SecurityHeadersRateLimitMiddleware(
            app=lambda *_: None,
            requests_per_minute=10,
            writes_per_minute=2,
        )
        self.assertEqual(middleware.requests_per_minute, 10)
        self.assertEqual(middleware.writes_per_minute, 2)

    def test_prune_removes_expired_buckets(self):
        middleware = SecurityHeadersRateLimitMiddleware(app=lambda *_: None)
        middleware.hits["old"].append(1.0)
        middleware._prune(now=1000.0)
        self.assertNotIn("old", middleware.hits)

    async def test_security_headers_are_added(self):
        middleware = SecurityHeadersRateLimitMiddleware(app=None)
        messages = await _asgi_request(middleware)
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertEqual(headers[b"x-frame-options"], b"DENY")
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertIn(b"strict-transport-security", headers)

    async def test_rate_limit_rejects_excess_requests_with_security_headers(self):
        middleware = SecurityHeadersRateLimitMiddleware(app=None, requests_per_minute=1)
        await _asgi_request(middleware, client=("192.0.2.10", 1000))
        messages = await _asgi_request(middleware, client=("192.0.2.10", 1000))
        self.assertEqual(messages[0]["status"], 429)
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertIn(b"retry-after", headers)

    async def test_write_and_read_limits_use_separate_buckets(self):
        middleware = SecurityHeadersRateLimitMiddleware(app=None, requests_per_minute=1, writes_per_minute=1)
        await _asgi_request(middleware, method="GET", client=("192.0.2.11", 1000))
        messages = await _asgi_request(middleware, method="POST", client=("192.0.2.11", 1000))
        self.assertEqual(messages[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()
