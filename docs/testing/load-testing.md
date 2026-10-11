# Load testing

[`backend/tests/load/`](https://github.com/HardMax71/Integr8sCode/tree/main/backend/tests/load) is a small load generator, not a pytest suite. It has two modes. Monkey mode throws random and half-broken requests at a fixed list of endpoints. User mode registers real users and runs realistic flows.

## Running

From `backend/`, with the stack up:

```bash
uv run python -m tests.load.cli --mode both --clients 30 --concurrency 10 --duration 180 --plots
```

Configuration comes only from these flags. There are no environment variables.

| Flag            | Default              | Meaning                                                         |
|-----------------|----------------------|-----------------------------------------------------------------|
| `--base-url`    | `https://[::1]:443`  | backend URL; TLS isn't verified                                 |
| `--mode`        | `both`               | `monkey`, `user` or `both`                                      |
| `--clients`     | 25                   | virtual clients; `both` gives half to each mode                 |
| `--concurrency` | 10                   | how many clients run at the same time                           |
| `--duration`    | 180                  | seconds per mode                                                |
| `--output`      | `tests/load/out`     | report directory, relative to the working directory             |
| `--plots`       | off                  | also write PNG charts next to the report                        |

In `both` mode the monkey run goes first and the user run starts after it, so the workload runs for about twice `--duration`. The preflight, requests still in flight at each deadline and the report add a little on top. Before either starts, the CLI checks `GET /api/v1/example-scripts` and prints the status, which catches a wrong URL or port early.

## What it calls

Monkey clients register and log in half of the time, then pick from `GET /auth/me`, `POST /auth/login`, `POST /auth/register`, `POST /execute`, `GET /k8s-limits`, `GET /example-scripts`, `GET /notifications`, `POST /notifications/mark-all-read`, `GET /user/settings/`, `PUT /user/settings/theme`, and two paths that don't exist. Bodies come from a Hypothesis JSON strategy, sometimes sent with the wrong content type, and the CSRF header is only sometimes included.

User clients register, log in, call `/auth/me`, then loop over weighted flows until the time is up:

| Flow                         | Weight | Calls                                                                    |
|------------------------------|--------|--------------------------------------------------------------------------|
| execute and get the result   | 5      | `POST /execute` with a valid or broken Python 3.11 script, then either the SSE stream `/events/executions/{id}` for about 8 seconds (up to 15 when idle, since the client checks the time per chunk and the server pings every 15) or a few polls of `/executions/{id}/result` |
| events and history           | 2      | `/user/executions`, then `/executions/{id}/events` for one of them       |
| saved scripts                | 2      | create, list, update and delete under `/scripts`                         |
| settings and notifications   | 2      | `/user/settings/`, `PUT /user/settings/theme`, `/notifications`, sometimes `mark-all-read` |

Every write after login sends `X-CSRF-Token` with the `csrf_token` from the login response, as the frontend does. The register and login requests themselves go without it.

## Reports

Each run writes `report_<mode>_<timestamp>.json`. Per endpoint it has the request count, errors, status code counts, latency (min, p50, p90, p99, max) overall and split by success and error, and bytes received. At the top level it has totals, exception types, runtime and a per-second timeline of requests and errors. `--plots` turns that into a timeline chart and per-endpoint latency and throughput charts, using matplotlib from the `load` dependency group.
