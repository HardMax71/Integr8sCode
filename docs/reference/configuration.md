# Configuration reference

The backend reads its non-secret configuration from TOML files, not from environment variables. `Settings` in `app/settings.py` builds it in this order, each layer overriding the one before:

1. `config.toml`, the base file committed to git
2. an optional override, `config.worker.toml` for the worker
3. four secrets from the environment: `SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD` and `REDIS_PASSWORD`

```python
Settings()                                              # config.toml + secrets
Settings(config_path="config.test.toml")                # tests
Settings(override_path="config.worker.toml")            # the worker
```

`Settings` uses `extra="forbid"`, so a key that isn't a field below stops the process at startup. `OTEL_SERVICE_NAME`, `OTEL_SERVICE_VERSION` and `OTEL_RESOURCE_ATTRIBUTES` are not fields: put them in TOML and nothing starts.

In the tables, the value is what applies with the shipped `config.toml`. The source says where it comes from: `config.toml`, the `Settings` default when the file doesn't set the key, or the environment.

## Secrets

For each secret, `Settings` takes the environment variable if it's set and non-empty, then the TOML value, then a dev default. Compose passes all four to every backend service through the `x-backend-secrets` anchor and has no defaults of its own: the values come from `.env` (locally a copy of `.env.example`, in production written by the deploy from the repository secrets), and compose refuses to start while one is empty.

| Variable | Purpose | Dev default |
|----------|---------|-------------|
| `SECRET_KEY` | JWT signing key, at least 32 characters | `CHANGE_ME_min_32_chars_long_!!!!` |
| `MONGO_USER` | MongoDB root user | `root` |
| `MONGO_PASSWORD` | MongoDB root password | `rootpassword` |
| `REDIS_PASSWORD` | Redis password | `redispassword` |

## Core and MongoDB

```toml
--8<-- "backend/config.toml:core"
```

| Key | Value | Source | What it does |
|-----|-------|--------|--------------|
| `PROJECT_NAME` | `integr8scode` | config.toml | FastAPI title and startup log |
| `API_V1_STR` | `/api/v1` | default | Prefix for every router |
| `ALGORITHM` | `HS256` | config.toml | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | config.toml | Seeds the `session_timeout_minutes` system setting, which sets the cookie lifetime |
| `MONGO_HOST`, `MONGO_PORT`, `MONGO_DB` | `mongo`, `27017`, `integr8scode` | config.toml | Used to build `MONGODB_URL` |
| `MONGODB_URL` | computed | | `mongodb://{user}:{password}@{host}:{port}/{db}?authSource=admin`, always overwritten by `Settings` |

## Kubernetes and execution limits

```toml
--8<-- "backend/config.toml:kubernetes"
```

| Key | Value | Source | What it does |
|-----|-------|--------|--------------|
| `KUBERNETES_CONFIG_PATH` | `/etc/rancher/k3s/k3s.yaml` | config.toml | k3s's own kubeconfig, read by the k8s worker and pod monitor |
| `KUBERNETES_API_SERVER` | `https://host.docker.internal:6443` | default | API address the client uses instead of the kubeconfig's `127.0.0.1` |
| `K8S_NAMESPACE` | `integr8scode` | config.toml | Namespace for executor pods; `default` is refused |
| `K8S_NAMESPACE_CPU_QUOTA`, `K8S_NAMESPACE_MEMORY_QUOTA` | `32`, `4Gi` | default | ResourceQuota on what all pods in that namespace request together |
| `K8S_POD_CPU_LIMIT` | `1000m` | config.toml | Seeds the `cpu_limit` system setting |
| `K8S_POD_MEMORY_LIMIT` | `128Mi` | config.toml | Seeds the `memory_limit` system setting; also the base for the memory utilization metric |
| `K8S_POD_EXECUTION_TIMEOUT` | `5` | config.toml | Seeds the `max_timeout_seconds` system setting |
| `K8S_POD_CPU_REQUEST` | `200m` | config.toml | CPU request on every executor pod |
| `K8S_POD_MEMORY_REQUEST` | `128Mi` | config.toml | Memory request on every executor pod |
| `K8S_POD_RUNTIME_CLASS_NAME` | none | default | `runtimeClassName` for executor pods, for example `gvisor` |
| `SUPPORTED_RUNTIMES` | from the registry | default | Built from `LANGUAGE_SPECS` in `app/runtime_registry.py` and returned by `/api/v1/k8s-limits`; leave it out of TOML |
| `EXAMPLE_SCRIPTS` | from the registry | default | Returned by `/api/v1/example-scripts` |
| `SERVER_HOST` | `0.0.0.0` | config.toml | See [Server](#server) |

Execution limits are not per request. CPU limit, memory limit and timeout are admin system settings stored in MongoDB, and every execution gets the current values. The first time any process reads the system settings and finds no document, it creates one from the three `K8S_POD_*` values above and `ACCESS_TOKEN_EXPIRE_MINUTES`. After that the stored document wins, so editing those TOML keys changes nothing until the document is removed. The TOML values are also the fallback when MongoDB can't be read. `max_concurrent_executions` starts at 10 and isn't in TOML. Each process caches the system settings for 60 seconds.

A language can raise its own pod's limits above the system settings. Go gets at least 1000m CPU, 320Mi memory, a 30 second timeout and 64Mi of `/tmp`. The rest are in `LANGUAGE_SPECS` in `app/runtime_registry.py`.

## Kafka

```toml
--8<-- "backend/config.toml:kafka"
```

| Key | Value | Source | What it does |
|-----|-------|--------|--------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:29092` | config.toml | Broker address |
| `KAFKA_REQUEST_TIMEOUT_MS` | `40000` | config.toml | Broker request timeout |
| `KAFKA_GRACEFUL_TIMEOUT` | `15.0` | default | Seconds FastStream waits for in-flight handlers on shutdown |

## SSE

```toml
--8<-- "backend/config.toml:sse"
```

| Key | Value | Source | What it does |
|-----|-------|--------|--------------|
| `SSE_CONSUMER_POOL_SIZE` | `10` | config.toml | `max_workers` of the `sse-bridge-pool` subscriber: how many events one API process handles at once |

## Tracing, metrics and logs

```toml
--8<-- "backend/config.toml:tracing"
```

```toml
--8<-- "backend/config.toml:service"
```

| Key | Value | Source | What it does |
|-----|-------|--------|--------------|
| `OTLP_TRACES_ENDPOINT` | `http://otel-collector:4317` | config.toml | OTLP gRPC endpoint for traces; empty turns export off (the default is empty) |
| `TRACING_SAMPLING_RATE` | `1.0` | config.toml | Fraction of traces kept, 0.0 to 1.0 (the default is 0.1) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | config.toml | OTLP endpoint for metrics and logs; unset turns both off |
| `SERVICE_NAME` | `integr8scode-backend` | config.toml | `service.name` on traces, metrics and logs, Kafka client id, event metadata; `config.worker.toml` sets `integr8scode-worker` |
| `SERVICE_VERSION` | `1.0.0` | config.toml | `service.version` on traces, metrics and logs |
| `ENVIRONMENT` | `development` | env var, then TOML | `deployment.environment` attribute; `test` also turns off notification throttling. Read from the environment like the secrets, so the production deploy writes `ENVIRONMENT=production` into `.env`. The collector gets it too and drops the browser's lines below `warning` in `production` |
| `HOSTNAME` | the machine's hostname | default | `service.instance.id` on logs and spans; inside a container that's the container ID |
| `LOG_LEVEL` | `INFO` | config.toml | structlog level |

While the OTel collector is down, the exporters log connection errors and the app keeps working.

## Server

```toml
--8<-- "backend/config.toml:server"
```

In the container, the backend runs gunicorn from the Dockerfile's entrypoint, which takes its worker count, threads and timeout from the environment and hardcodes the rest. The TOML server keys only apply when you start the API with `uv run python -m app.main`, which runs uvicorn directly.

| Key | Value | Source | What it does |
|-----|-------|--------|--------------|
| `WEB_CONCURRENCY` | `2` | config.toml | Uvicorn workers under `python -m app.main` |
| `WEB_TIMEOUT` | `60` | config.toml | Uvicorn keep-alive timeout under `python -m app.main` |
| `WEB_BACKLOG` | `2048` | config.toml | Uvicorn backlog under `python -m app.main` |
| `SERVER_HOST` | `0.0.0.0` | config.toml | Bind address under `python -m app.main` |
| `SERVER_PORT` | `443` | default | Port under `python -m app.main` |
| `SSL_KEYFILE`, `SSL_CERTFILE` | `/app/certs/key/server.key`, `/app/certs/cert/server.crt` | default | TLS files under `python -m app.main`; the container's entrypoint makes them on first start |
| `BCRYPT_ROUNDS` | `12` | config.toml | bcrypt cost for passwords |
| `REDIS_MAX_CONNECTIONS` | `200` | config.toml | Redis connection pool size |

## Keys only in Settings

These have no entry in `config.toml`, so the `Settings` default applies.

| Key | Value | What it does |
|-----|-------|--------------|
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | `redis`, `6379`, `0` | Redis connection |
| `REDIS_SSL` | `false` | TLS to Redis |
| `REDIS_DECODE_RESPONSES` | `true` | Must stay true; the type only allows `true` |
| `RATE_LIMIT_ENABLED` | `true` | `false` turns the rate limit middleware off |
| `RATE_LIMIT_REDIS_PREFIX` | `rate_limit:` | Prefix for rate limit keys in Redis |
| `NOTIF_THROTTLE_WINDOW_HOURS` | `1` | Notification throttle window |
| `NOTIF_THROTTLE_MAX_PER_HOUR` | `5` | Notifications allowed per user per window |
| `DEVELOPMENT_MODE` | `false` | `true` serves `/openapi.json`, `/docs` and `/redoc` |

`CORS_ORIGINS` is the list in config.toml, and it replaces the `Settings` default list.

## Worker override

The worker loads `config.worker.toml` next to `config.toml`. It sets one key, `SERVICE_NAME = "integr8scode-worker"`, so traces, logs and metrics tell the worker apart from the API.

## Test configuration

`config.test.toml` is a full config file that tests load with `Settings(config_path="config.test.toml")`. Compared to `config.toml` it sets `ENVIRONMENT = "test"`, turns rate limiting off, uses 4 bcrypt rounds, an SSE pool size of 1 and `WARNING` logs, and exports no traces, metrics or logs. It also lowers `KAFKA_REQUEST_TIMEOUT_MS` to 5000 and `KAFKA_GRACEFUL_TIMEOUT` to 5.0, so brokers stop faster when a test session ends.

## Compose environment

A few variables are read by containers other than the backend's `Settings`:

| Variable | Default | Read by |
|----------|---------|---------|
| `WEB_CONCURRENCY`, `WEB_THREADS`, `WEB_TIMEOUT` | `2`, `4`, `60` | gunicorn in the backend container |
| `DEFAULT_USER_PASSWORD`, `ADMIN_USER_PASSWORD` | none; `.env.example` has `user123`, `admin123` | `scripts.seed_users` in the backend container, which creates the `user` and `admin` accounts before gunicorn starts |
| `MONGO_MONITOR_USER`, `MONGO_MONITOR_PASSWORD` | `otel-monitor`; none for the password, `.env.example` has `monitorpassword` | `scripts.seed_users` creates this least-privilege MongoDB user, and the OTel collector's mongodb receiver logs in with it |
| `GRAFANA_ROOT_URL` | `http://localhost:3000/` | Grafana's root URL, and the frontend's `GRAFANA_PUBLIC_URL`, where `/grafana` redirects |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | `admin`; none for the password, `.env.example` has `admin123` | Grafana |
| `GF_SMTP_HOST`, `MAILJET_API_KEY`, `MAILJET_SECRET_KEY` | empty | Grafana, as the SMTP server and login for alert mail. The release deploy fills the host from the `MAILJET_HOST` secret |
| `MAILJET_FROM_ADDRESS`, `GRAFANA_ALERT_RECIPIENTS` | `noreply@integr8scode.cc` | Grafana, as the alert mail sender and recipients |
| `IMAGE_TAG` | `latest` | Image tag for every service built from this repo |

The password defaults are for local runs. Compose falls back to a default whenever its variable is unset or empty, so a deployment has to set every password itself.
