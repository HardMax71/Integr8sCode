# Environment Variables

All configuration is done through environment variables loaded from `.env` files. Copy `backend/.env` to get started and adjust as needed.

The code blocks below show the actual `backend/.env` development configuration. The legend tables show what the app uses if a variable is **not set at all** — these are the `settings.py` defaults, which may differ from the dev config.

## Core

```bash
--8<-- "backend/.env:1:9"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `PROJECT_NAME` | Application name for logs and metadata | `integr8scode` |
    | `DATABASE_NAME` | MongoDB database name | `integr8scode_db` |
    | `SECRET_KEY` | JWT signing key. **Required**, min 32 chars | — |
    | `ALGORITHM` | JWT signing algorithm | `HS256` |
    | `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime in minutes | `1440` (24h) |
    | `MONGO_ROOT_USER` | MongoDB admin username | `root` |
    | `MONGO_ROOT_PASSWORD` | MongoDB admin password | `rootpassword` |
    | `MONGODB_URL` | MongoDB connection string | `mongodb://mongo:27017/integr8scode` |

## Kubernetes

```bash
--8<-- "backend/.env:10:17"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
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

```bash
--8<-- "backend/.env:19:31"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `KAFKA_BOOTSTRAP_SERVERS` | Broker addresses (comma-separated) | `kafka:29092` |
    | `SCHEMA_REGISTRY_URL` | Confluent Schema Registry URL | `http://schema-registry:8081` |
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

```bash
--8<-- "backend/.env:32:34"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `SSE_CONSUMER_POOL_SIZE` | Number of Kafka consumers for SSE streaming | `10` |
    | `SSE_HEARTBEAT_INTERVAL` | Keepalive interval in seconds | `30` |

## Tracing (OpenTelemetry)

```bash
--8<-- "backend/.env:39:45"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `ENABLE_TRACING` | Enable distributed tracing | `true` |
    | `JAEGER_AGENT_HOST` | Jaeger agent hostname | `jaeger` |
    | `JAEGER_AGENT_PORT` | Jaeger agent UDP port | `6831` |
    | `TRACING_SERVICE_NAME` | Service name in traces | `integr8scode-backend` |
    | `TRACING_SERVICE_VERSION` | Version in trace metadata | `1.0.0` |
    | `TRACING_SAMPLING_RATE` | Sample rate (0.0–1.0) | `0.1` |

## Dead Letter Queue

```bash
--8<-- "backend/.env:47:53"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `DLQ_RETRY_MAX_ATTEMPTS` | Retries before archiving | `5` |
    | `DLQ_RETRY_BASE_DELAY_SECONDS` | Base delay between retries | `60` |
    | `DLQ_RETRY_MAX_DELAY_SECONDS` | Max delay (backoff cap) | `3600` |
    | `DLQ_RETENTION_DAYS` | Days to keep DLQ messages | `7` |
    | `DLQ_WARNING_THRESHOLD` | Warning alert threshold | `100` |
    | `DLQ_CRITICAL_THRESHOLD` | Critical alert threshold | `1000` |

## Service & OTEL

```bash
--8<-- "backend/.env:55:66"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `APP_URL` | Public URL for notifications | `https://integr8scode.cc` |
    | `SERVICE_NAME` | Service identifier | `integr8scode-backend` |
    | `SERVICE_VERSION` | Service version | `1.0.0` |
    | `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | — |
    | `OTEL_SERVICE_NAME` | OTEL service name | — |
    | `OTEL_SERVICE_VERSION` | OTEL service version | — |
    | `OTEL_RESOURCE_ATTRIBUTES` | Additional resource attributes | — |

## Server

```bash
--8<-- "backend/.env:68:84"
```

??? info "Legend"
    | Variable | Description | If unset |
    |----------|-------------|---------|
    | `WEB_CONCURRENCY` | Gunicorn worker processes | `4` |
    | `WEB_THREADS` | Threads per worker | `1` |
    | `WEB_TIMEOUT` | Request timeout in seconds | `60` |
    | `WEB_BACKLOG` | TCP connection backlog | `2048` |
    | `SERVER_HOST` | Bind address | `localhost` |
    | `BCRYPT_ROUNDS` | Password hashing rounds | `12` |
    | `REDIS_MAX_CONNECTIONS` | Redis connection pool size | `200` |
