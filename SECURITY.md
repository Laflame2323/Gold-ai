# Gold AI Security Baseline

## Implemented baseline (research branch)

- Browser CORS is restricted to the known Gold AI Vercel origins and localhost development origins. CORS is not authentication and does not protect non-browser clients.
- API responses receive defensive headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and HSTS.
- Research and broker API responses are marked `Cache-Control: no-store`.
- A per-process request limiter is enabled (120 reads/minute and 30 writes/minute per ASGI client address).
- MT5 candle and tick ingestion continue to require the private `X-MT5-Token` and constant-time token comparison.
- Supabase credentials remain backend-only. No service-role/secret key belongs in frontend code, browser storage, Git, or logs.

## Verified database posture (2026-11-20)

- The Supabase advisor reports RLS enabled on the ten inspected public tables.
- The advisor reports those tables have no RLS policies.
- Direct catalog checks returned no table grants to `anon`, `authenticated`, or `PUBLIC`.
- The current backend uses its private server-side Supabase key for database access. Keep that key private.

Do not add broad public RLS policies just to silence the advisor. If browser access is introduced, use Supabase Auth and explicit least-privilege policies scoped to the authenticated user's rows. Re-check grants, views, functions, and Storage separately.

## Important limitations

- The in-process limiter is not shared between Render instances and resets on restart. It is a baseline abuse guard only. Add an edge/WAF limit or shared Redis/Upstash limiter before horizontal scaling.
- CORS is not an access-control boundary. Several research GET endpoints are currently public; sensitive research endpoints need authentication before multi-user or private deployment.
- Dashboard authentication, MFA, role-based access control, audit-event persistence, key rotation, backup restore drills, and model artifact signing are not yet implemented.
- HSTS assumes the production service is HTTPS. Local development should use HTTPS when testing strict browser behavior.
- Do not enable automated trading or model self-modification as a side effect of these security changes.

## Required next phases

1. Choose single-owner private access or multi-user access.
2. Add Supabase Auth with short-lived sessions, MFA where available, server-side JWT verification, and explicit owner/admin roles.
3. Protect private research, model-management, and assistant endpoints. Keep only health/status endpoints public where needed.
4. Create append-only audit events for sign-ins, failed access, data exports, model changes, training runs, and configuration changes. Never log secrets or full credentials.
5. Verify RLS and SQL grants for every exposed table, view, function, and Storage bucket. Use owner-scoped policies; do not rely on `TO authenticated` alone.
6. Add shared edge rate limits, request-size limits, bot protection, and alerts.
7. Add encrypted backups, restore testing, dependency scanning, secret scanning, and signed/versioned model artifacts.
8. Add AI-specific controls: treat news and imported data as untrusted, defend against prompt injection, validate model outputs, prevent training-data poisoning, and keep all trading actions behind explicit human approval and hard risk limits.

## Security tests

Run from the backend directory:

    python -m unittest test_security_controls.py -v

These tests cover the baseline limiter helper only; they are not a penetration test or proof of production security.
