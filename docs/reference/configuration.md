# Configuration Reference

Non-secret configuration is loaded from TOML files. Secrets come from environment variables with dev defaults. The `Settings` class (`app/settings.py`) reads in this order, each layer overriding the previous:

1. **`config.toml`** — base settings, committed to git (no secrets)
2. **per-worker override** — optional TOML file for service-specific settings (e.g. `config.saga-orchestrator.toml`)
3. **Environment variables** for secrets: `SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `REDIS_PASSWORD`

```python
# Default — reads config.toml + env vars
Settings()

# Tests — reads config.test.toml + env vars
Settings(config_path="config.test.toml")

# Worker — reads config.toml + worker override + env vars
Settings(override_path="config.saga-orchestrator.toml")
```

## Secrets

Secrets are read from environment variables. Dev defaults are built in so local development requires zero configuration:

| Variable | Description | Dev default |
|----------|-------------|-------------|
| `SECRET_KEY` | JWT signing key (min 32 chars) | `CHANGE_ME_min_32_chars_long_!!!!` |
| `MONGO_USER` | MongoDB root username | `root` |
| `MONGO_PASSWORD` | MongoDB root password | `rootpassword` |
| `REDIS_PASSWORD` | Redis password | `redispassword` |

Docker Compose passes these via a shared `x-backend-secrets` YAML anchor to all backend services. For production, set the env vars through GitHub Actions secrets or your deployment platform.

## Core

```toml
--8<-- "backend/config.toml:core"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `PROJECT_NAME` | Application name for logs and metadata | `integr8scode` |
    | `DATABASE_NAME` | MongoDB database name | `integr8scode_db` |
    | `SECRET_KEY` | JWT signing key, min 32 chars. **From env var** | `CHANGE_ME_min_32_chars_long_!!!!` |
    | `ALGORITHM` | JWT signing algorithm | `HS256` |
    | `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime in minutes | `1440` (24h) |
    | `MONGODB_URL` | MongoDB connection string. **Built from `MONGO_USER`/`MONGO_PASSWORD` env vars + `MONGO_HOST`/`MONGO_PORT`/`MONGO_DB` from TOML** | (computed) |

## Kubernetes

```toml
--8<-- "backend/config.toml:kubernetes"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `KUBERNETES_CONFIG_PATH` | Path to kubeconfig | `~/.kube/config` |
    | `KUBERNETES_CA_CERTIFICATE_PATH` | Custom CA cert for K8s API | — |
    | `K8S_POD_CPU_LIMIT` | CPU limit per pod | `1000m` |
    | `K8S_POD_MEMORY_LIMIT` | Memory limit per pod | `128Mi` |
    | `K8S_POD_CPU_REQUEST` | CPU request (guaranteed) | `200m` |
    | `K8S_POD_MEMORY_REQUEST` | Memory request (guaranteed) | `128Mi` |
    | `K8S_POD_EXECUTION_TIMEOUT` | Max execution time in seconds | `300` |
    | `K8S_NAMESPACE` | Namespace for executor pods | `integr8scode` |
    | `RATE_LIMITS` | Default rate limit string | `100/minute` |

## Kafka

```toml
--8<-- "backend/config.toml:kafka"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `KAFKA_BOOTSTRAP_SERVERS` | Broker addresses (comma-separated) | `kafka:29092` |
    | `ENABLE_EVENT_STREAMING` | Enable Kafka events | `false` |
    | `EVENT_RETENTION_DAYS` | Days to retain events in MongoDB | `30` |
    | `KAFKA_CONSUMER_GROUP_ID` | Consumer group ID | `integr8scode-backend` |
    | `KAFKA_AUTO_OFFSET_RESET` | Where to start if no offset | `earliest` |
    | `KAFKA_ENABLE_AUTO_COMMIT` | Auto-commit offsets | `true` |
    | `KAFKA_SESSION_TIMEOUT_MS` | Session timeout before rebalance | `45000` |
    | `KAFKA_HEARTBEAT_INTERVAL_MS` | Heartbeat frequency | `10000` |
    | `KAFKA_REQUEST_TIMEOUT_MS` | Broker request timeout | `40000` |
    | `KAFKA_MAX_POLL_RECORDS` | Max records per poll | `500` |

## SSE (Server-Sent Events)

```toml
--8<-- "backend/config.toml:sse"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `SSE_CONSUMER_POOL_SIZE` | Number of Kafka consumers for SSE streaming | `10` |
    | `SSE_HEARTBEAT_INTERVAL` | Keepalive interval in seconds | `30` |

## Tracing (OpenTelemetry)

```toml
--8<-- "backend/config.toml:tracing"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `OTLP_TRACES_ENDPOINT` | OTLP gRPC endpoint; tracing is enabled when non-empty | Code default: `""` (disabled); config.toml: `http://jaeger:4317` |
    | `TRACING_SERVICE_NAME` | Service name in traces | `integr8scode-backend` |
    | `TRACING_SERVICE_VERSION` | Version in trace metadata | `1.0.0` |
    | `TRACING_SAMPLING_RATE` | Sample rate (0.0-1.0) | `1.0` in config.toml (`0.1` code default) |

## Dead Letter Queue

```toml
--8<-- "backend/config.toml:dlq"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `DLQ_RETRY_MAX_ATTEMPTS` | Retries before archiving | `5` |
    | `DLQ_RETRY_BASE_DELAY_SECONDS` | Base delay between retries | `60` |
    | `DLQ_RETRY_MAX_DELAY_SECONDS` | Max delay (backoff cap) | `3600` |
    | `DLQ_RETENTION_DAYS` | Days to keep DLQ messages | `7` |
    | `DLQ_WARNING_THRESHOLD` | Warning alert threshold | `100` |
    | `DLQ_CRITICAL_THRESHOLD` | Critical alert threshold | `1000` |

## Service & OTEL

```toml
--8<-- "backend/config.toml:service"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `APP_URL` | Public URL for notifications | `https://integr8scode.cc` |
    | `SERVICE_NAME` | Service identifier | `integr8scode-backend` |
    | `SERVICE_VERSION` | Service version | `1.0.0` |
    | `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | — |
    | `OTEL_SERVICE_NAME` | OTEL service name | — |
    | `OTEL_SERVICE_VERSION` | OTEL service version | — |
    | `OTEL_RESOURCE_ATTRIBUTES` | Additional resource attributes | — |

## Server

```toml
--8<-- "backend/config.toml:server"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `WEB_CONCURRENCY` | Gunicorn worker processes | `4` |
    | `WEB_THREADS` | Threads per worker | `1` |
    | `WEB_TIMEOUT` | Request timeout in seconds | `60` |
    | `WEB_BACKLOG` | TCP connection backlog | `2048` |
    | `SERVER_HOST` | Bind address | `localhost` |
    | `BCRYPT_ROUNDS` | Password hashing rounds | `12` |
    | `REDIS_MAX_CONNECTIONS` | Redis connection pool size | `200` |

## Worker overrides

Each worker runs with a small override TOML that sets `TRACING_SERVICE_NAME` and `KAFKA_CONSUMER_GROUP_ID`. These are mounted alongside `config.toml` in Docker Compose:

| File | Service |
|------|---------|
| `config.k8s-worker.toml` | Kubernetes pod manager |
| `config.pod-monitor.toml` | Pod status watcher |
| `config.result-processor.toml` | Result processor |
| `config.saga-orchestrator.toml` | Saga orchestrator |
| `config.event-replay.toml` | Event replay |
| `config.dlq-processor.toml` | Dead letter queue processor |

## Test configuration

`config.test.toml` is a full config file tuned for fast test execution (lower bcrypt rounds, relaxed rate limits, shorter Kafka timeouts). Tests load it with:

```python
Settings(config_path="config.test.toml")
```

Secrets come from environment variables with dev defaults — no extra setup needed in CI or locally.
