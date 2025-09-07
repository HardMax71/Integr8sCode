# Backend Load & Monkey Test Suite

This suite provides two complementary stress tools:

- Monkey tests: fuzz endpoints with random methods, bodies, and parameters to test durability and correctness under garbage requests (with and without auth/CSRF).
- User load tests: authenticate as normal users and exercise the user‑accessible API (no admin routes) with realistic flows.

Quick start

1) Ensure backend is running locally at https://localhost:443 (self‑signed cert OK).

2) Run the CLI (uses env vars for config). By default it runs ~3 minutes:

   python -m tests.load.cli --mode both --clients 30 --concurrency 10 --duration 180

   Options:
   - --base-url https://localhost:443
   - --mode monkey|user|both
   - --clients N (virtual clients)
   - --concurrency M (parallel tasks)
   - --duration seconds (default 180)
   - --output tests/load/out

3) Reports are saved as JSON under backend/tests/load/out/report_<mode>_<timestamp>.json

Property-based fuzz tests (Hypothesis)

- Run pytest to exercise property tests that shrink failing inputs:

  pytest -q backend/tests/load/test_property_monkey.py

- Tests included:
  - test_register_never_500: Random valid user payloads must not yield 5xx.
  - test_alertmanager_webhook_never_500: Random (schema-like) Alertmanager payloads must not yield 5xx.

These tests provide minimal counterexamples if a 5xx occurs.

Environment variables (optional)

- LOAD_BASE_URL (default https://localhost:443)
- LOAD_API_PREFIX (default /api/v1)
- LOAD_VERIFY_TLS (true/false; default false)
- LOAD_MODE (monkey|user|both; default both)
- LOAD_CLIENTS (default 25)
- LOAD_CONCURRENCY (default 10)
- LOAD_DURATION (seconds; default 180)
- LOAD_RAMP (seconds; reserved for future)

- LOAD_AUTO_REGISTER (true/false; default true)
- LOAD_USER_PREFIX (default loaduser)
- LOAD_USER_DOMAIN (default example.com)
- LOAD_USER_PASSWORD (default testpass123!)

What it does

- Auth: register/login and keep cookies+CSRF token per client.
- Executions: submit scripts (valid/invalid), stream SSE or poll results, fetch events.
- Saved scripts: create/list/update/delete.
- User settings: get/update.
- Notifications: list/mark‑all‑read.

Metrics

- Per endpoint: count, error count, status code distribution, latency p50/p90/p99, bytes received.
- Global: total requests, total errors, exception types, runtime.

Notes

- For write endpoints, the client sends X‑CSRF‑Token from the csrf_token cookie (double‑submit pattern).
- SSE streams are sampled with a short read window (default ~8–10s) to avoid lingering connections.
- The suite intentionally avoids admin routes in user mode.
