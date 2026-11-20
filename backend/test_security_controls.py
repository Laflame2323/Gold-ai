import unittest
from security_controls import SecurityHeadersRateLimitMiddleware


class SecurityControlsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
