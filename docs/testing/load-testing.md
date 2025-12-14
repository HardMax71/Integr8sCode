# Load testing

This suite provides two complementary stress tools. Monkey tests fuzz endpoints with random methods, bodies, and parameters to test durability and correctness under garbage requests (with and without auth/CSRF). User load tests authenticate as normal users and exercise the user-accessible API with realistic flows, avoiding admin routes.

## Quick start

Ensure the backend is running locally at `https://localhost:443` (self-signed cert is fine). Run the CLI with default settings for a ~3 minute test:

```bash
python -m tests.load.cli --mode both --clients 30 --concurrency 10 --duration 180
```

Available options:

| Option | Description |
|--------|-------------|
| `--base-url` | Target URL (default: `https://localhost:443`) |
| `--mode` | `monkey`, `user`, or `both` |
| `--clients` | Number of virtual clients |
| `--concurrency` | Parallel tasks |
| `--duration` | Test duration in seconds (default: 180) |
| `--output` | Output directory (default: `tests/load/out`) |

Reports are saved as JSON under `backend/tests/load/out/report_<mode>_<timestamp>.json`.

## Property-based fuzz tests

Run Hypothesis-powered property tests that shrink failing inputs to minimal counterexamples:

```bash
pytest -q backend/tests/load/test_property_monkey.py
```

Tests included:

- `test_register_never_500` — random valid user payloads must not yield 5xx
- `test_grafana_webhook_never_500` — random Grafana-like payloads must not yield 5xx

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOAD_BASE_URL` | `https://localhost:443` | Target URL |
| `LOAD_API_PREFIX` | `/api/v1` | API prefix |
| `LOAD_VERIFY_TLS` | `false` | Verify TLS certificates |
| `LOAD_MODE` | `both` | Test mode |
| `LOAD_CLIENTS` | `25` | Virtual clients |
| `LOAD_CONCURRENCY` | `10` | Parallel tasks |
| `LOAD_DURATION` | `180` | Duration in seconds |
| `LOAD_AUTO_REGISTER` | `true` | Auto-register users |
| `LOAD_USER_PREFIX` | `loaduser` | Username prefix |
| `LOAD_USER_DOMAIN` | `example.com` | Email domain |
| `LOAD_USER_PASSWORD` | `testpass123!` | User password |

## What it tests

The suite covers authentication (register/login with cookies and CSRF tokens), executions (submit scripts, stream SSE or poll results, fetch events), saved scripts (CRUD operations), user settings (get/update), and notifications (list/mark-all-read).

## Metrics

Each endpoint reports count, error count, status code distribution, latency percentiles (p50/p90/p99), and bytes received. Global metrics include total requests, total errors, exception types, and runtime.

## Notes

For write endpoints, the client sends `X-CSRF-Token` from the `csrf_token` cookie (double-submit pattern). SSE streams are sampled with a short read window (~8-10s) to avoid lingering connections.
