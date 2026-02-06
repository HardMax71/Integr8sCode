# Configuration Reference

All backend configuration is loaded from TOML files — no environment variables, no `.env` files. The `Settings` class (`app/settings.py`) reads files in this order, each layer overriding the previous:

1. **`config.toml`** — base settings, committed to git (no secrets)
2. **`secrets.toml`** — sensitive values (`SECRET_KEY`, `MONGODB_URL`), gitignored
3. **per-worker override** — optional TOML file for service-specific settings (e.g. `config.coordinator.toml`)

```python
# Default — reads config.toml + secrets.toml
Settings()

# Tests — reads config.test.toml + secrets.toml
Settings(config_path="config.test.toml")

# Worker — reads config.toml + secrets.toml + worker override
Settings(override_path="config.coordinator.toml")
```

## Secrets

Credentials live in `secrets.toml`, which is gitignored. A committed template with development defaults is provided:

```bash
cp backend/secrets.example.toml backend/secrets.toml
```

```toml
--8<-- "backend/secrets.example.toml"
```

For production, mount `secrets.toml` from a Kubernetes Secret at `/app/secrets.toml`. In CI, generate it from repository secrets (see the template comments for an example).

## Core

```toml
--8<-- "backend/config.toml:1:9"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `PROJECT_NAME` | Application name for logs and metadata | `integr8scode` |
    | `DATABASE_NAME` | MongoDB database name | `integr8scode_db` |
    | `SECRET_KEY` | JWT signing key, min 32 chars. **Lives in `secrets.toml`** | — (required) |
    | `ALGORITHM` | JWT signing algorithm | `HS256` |
    | `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime in minutes | `1440` (24h) |
    | `MONGODB_URL` | MongoDB connection string. **Lives in `secrets.toml`** | `mongodb://mongo:27017/integr8scode` |

## Kubernetes

```toml
--8<-- "backend/config.toml:11:20"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `KUBERNETES_CONFIG_PATH` | Path to kubeconfig | `~/.kube/config` |
    | `KUBERNETES_CA_CERTIFICATE_PATH` | Custom CA cert for K8s API | — |
    | `K8S_POD_CPU_LIMIT` | CPU limit per pod | `1000m` |
    | `K8S_POD_MEMORY_LIMIT` | Memory limit per pod | `128Mi` |
    | `K8S_POD_CPU_REQUEST` | CPU request (guaranteed) | `1000m` |
    | `K8S_POD_MEMORY_REQUEST` | Memory request (guaranteed) | `128Mi` |
    | `K8S_POD_EXECUTION_TIMEOUT` | Max execution time in seconds | `300` |
    | `K8S_NAMESPACE` | Namespace for executor pods | `integr8scode` |
    | `RATE_LIMITS` | Default rate limit string | `100/minute` |

## Kafka

```toml
--8<-- "backend/config.toml:26:37"
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
--8<-- "backend/config.toml:39:40"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `SSE_CONSUMER_POOL_SIZE` | Number of Kafka consumers for SSE streaming | `10` |
    | `SSE_HEARTBEAT_INTERVAL` | Keepalive interval in seconds | `30` |

## Tracing (OpenTelemetry)

```toml
--8<-- "backend/config.toml:45:51"
```

??? info "Legend"
    | Key | Description | Default |
    |-----|-------------|---------|
    | `ENABLE_TRACING` | Enable distributed tracing | `true` |
    | `JAEGER_AGENT_HOST` | Jaeger agent hostname | `jaeger` |
    | `JAEGER_AGENT_PORT` | Jaeger agent UDP port | `6831` |
    | `TRACING_SERVICE_NAME` | Service name in traces | `integr8scode-backend` |
    | `TRACING_SERVICE_VERSION` | Version in trace metadata | `1.0.0` |
    | `TRACING_SAMPLING_RATE` | Sample rate (0.0-1.0) | `0.1` |

## Dead Letter Queue

```toml
--8<-- "backend/config.toml:53:59"
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
--8<-- "backend/config.toml:61:70"
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
--8<-- "backend/config.toml:72:80"
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

Each worker runs with a small override TOML that sets `TRACING_SERVICE_NAME` and `KAFKA_CONSUMER_GROUP_ID`. These are mounted alongside `config.toml` and `secrets.toml` in Docker Compose:

| File | Service |
|------|---------|
| `config.coordinator.toml` | Execution coordinator |
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

Secrets are still loaded from `secrets.toml`. In CI, the workflow copies the example template:

```bash
cp backend/secrets.example.toml backend/secrets.toml
```
