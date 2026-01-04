# Environment Variables Reference

Complete reference of all environment variables used by the Integr8sCode backend.

## Core Configuration

| Variable                      | Default                              | Description                         |
|-------------------------------|--------------------------------------|-------------------------------------|
| `PROJECT_NAME`                | `integr8scode`                       | Application name                    |
| `DATABASE_NAME`               | `integr8scode_db`                    | MongoDB database name               |
| `MONGODB_URL`                 | `mongodb://mongo:27017/integr8scode` | MongoDB connection URL              |
| `SECRET_KEY`                  | *required*                           | JWT signing key (min 32 characters) |
| `ALGORITHM`                   | `HS256`                              | JWT signing algorithm               |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440`                               | Token lifetime (24 hours)           |
| `API_V1_STR`                  | `/api/v1`                            | API version prefix                  |
| `APP_URL`                     | `https://integr8scode.cc`            | Public application URL              |

## Server Configuration

| Variable          | Default                 | Description               |
|-------------------|-------------------------|---------------------------|
| `SERVER_HOST`     | `localhost`             | Server bind address       |
| `SERVER_PORT`     | `443`                   | Server port               |
| `SSL_KEYFILE`     | `/app/certs/server.key` | SSL private key path      |
| `SSL_CERTFILE`    | `/app/certs/server.crt` | SSL certificate path      |
| `WEB_CONCURRENCY` | `4`                     | Gunicorn worker count     |
| `WEB_THREADS`     | `1`                     | Threads per worker        |
| `WEB_TIMEOUT`     | `60`                    | Request timeout (seconds) |
| `WEB_BACKLOG`     | `2048`                  | Connection backlog        |

## Kubernetes Configuration

| Variable                         | Default          | Description                 |
|----------------------------------|------------------|-----------------------------|
| `KUBERNETES_CONFIG_PATH`         | `~/.kube/config` | Kubeconfig file path        |
| `KUBERNETES_CA_CERTIFICATE_PATH` | *none*           | Custom CA certificate path  |
| `K8S_POD_CPU_LIMIT`              | `1000m`          | Pod CPU limit               |
| `K8S_POD_MEMORY_LIMIT`           | `128Mi`          | Pod memory limit            |
| `K8S_POD_CPU_REQUEST`            | `1000m`          | Pod CPU request             |
| `K8S_POD_MEMORY_REQUEST`         | `128Mi`          | Pod memory request          |
| `K8S_POD_EXECUTION_TIMEOUT`      | `300`            | Execution timeout (seconds) |
| `K8S_POD_PRIORITY_CLASS_NAME`    | *none*           | Pod priority class          |

## Kafka Configuration

| Variable                   | Default                       | Description                         |
|----------------------------|-------------------------------|-------------------------------------|
| `KAFKA_BOOTSTRAP_SERVERS`  | `kafka:29092`                 | Kafka broker addresses              |
| `SCHEMA_REGISTRY_URL`      | `http://schema-registry:8081` | Schema Registry URL                 |
| `SCHEMA_REGISTRY_AUTH`     | *none*                        | Registry auth (`username:password`) |
| `ENABLE_EVENT_STREAMING`   | `false`                       | Enable Kafka event streaming        |
| `EVENT_RETENTION_DAYS`     | `30`                          | Event retention period              |
| `KAFKA_TOPIC_PREFIX`       | `pref`                        | Topic name prefix                   |
| `KAFKA_GROUP_SUFFIX`       | `suff`                        | Consumer group suffix               |
| `KAFKA_CONSUMER_GROUP_ID`  | `integr8scode-backend`        | Default consumer group              |
| `KAFKA_AUTO_OFFSET_RESET`  | `earliest`                    | Offset reset policy                 |
| `KAFKA_ENABLE_AUTO_COMMIT` | `true`                        | Auto-commit offsets                 |
| `KAFKA_SESSION_TIMEOUT_MS` | `30000`                       | Session timeout                     |
| `KAFKA_MAX_POLL_RECORDS`   | `500`                         | Max poll batch size                 |

## Redis Configuration

| Variable                 | Default | Description                 |
|--------------------------|---------|-----------------------------|
| `REDIS_HOST`             | `redis` | Redis server host           |
| `REDIS_PORT`             | `6379`  | Redis server port           |
| `REDIS_DB`               | `0`     | Redis database number       |
| `REDIS_PASSWORD`         | *none*  | Redis password              |
| `REDIS_SSL`              | `false` | Enable SSL/TLS              |
| `REDIS_MAX_CONNECTIONS`  | `50`    | Connection pool size        |
| `REDIS_DECODE_RESPONSES` | `true`  | Decode responses to strings |

## Rate Limiting Configuration

| Variable                      | Default          | Description                                    |
|-------------------------------|------------------|------------------------------------------------|
| `RATE_LIMIT_ENABLED`          | `true`           | Enable rate limiting                           |
| `RATE_LIMITS`                 | `100/minute`     | Default rate limit string                      |
| `RATE_LIMIT_DEFAULT_REQUESTS` | `100`            | Default request limit                          |
| `RATE_LIMIT_DEFAULT_WINDOW`   | `60`             | Default window (seconds)                       |
| `RATE_LIMIT_BURST_MULTIPLIER` | `1.5`            | Token bucket burst factor                      |
| `RATE_LIMIT_REDIS_PREFIX`     | `rate_limit:`    | Redis key prefix                               |
| `RATE_LIMIT_ALGORITHM`        | `sliding_window` | Algorithm (`sliding_window` or `token_bucket`) |

## SSE Configuration

| Variable                             | Default | Description                  |
|--------------------------------------|---------|------------------------------|
| `SSE_CONSUMER_POOL_SIZE`             | `10`    | Kafka consumer pool size     |
| `SSE_HEARTBEAT_INTERVAL`             | `30`    | Heartbeat interval (seconds) |
| `WEBSOCKET_PING_INTERVAL`            | `30`    | Connection ping interval     |
| `WEBSOCKET_PING_TIMEOUT`             | `10`    | Ping timeout                 |
| `WEBSOCKET_MAX_CONNECTIONS_PER_USER` | `5`     | Max connections per user     |
| `WEBSOCKET_STALE_CONNECTION_TIMEOUT` | `300`   | Stale connection timeout     |

## Notification Configuration

| Variable                      | Default | Description                   |
|-------------------------------|---------|-------------------------------|
| `NOTIF_THROTTLE_WINDOW_HOURS` | `1`     | Throttle window (hours)       |
| `NOTIF_THROTTLE_MAX_PER_HOUR` | `5`     | Max notifications per hour    |
| `NOTIF_PENDING_BATCH_SIZE`    | `10`    | Pending batch size            |
| `NOTIF_OLD_DAYS`              | `30`    | Notification retention (days) |
| `NOTIF_RETRY_DELAY_MINUTES`   | `5`     | Retry delay (minutes)         |

## Dead Letter Queue Configuration

| Variable                       | Default  | Description              |
|--------------------------------|----------|--------------------------|
| `DLQ_RETRY_MAX_ATTEMPTS`       | `5`      | Maximum retry attempts   |
| `DLQ_RETRY_BASE_DELAY_SECONDS` | `60.0`   | Base retry delay         |
| `DLQ_RETRY_MAX_DELAY_SECONDS`  | `3600.0` | Maximum retry delay      |
| `DLQ_RETENTION_DAYS`           | `7`      | DLQ message retention    |
| `DLQ_WARNING_THRESHOLD`        | `100`    | Warning threshold count  |
| `DLQ_CRITICAL_THRESHOLD`       | `1000`   | Critical threshold count |

## Tracing Configuration (OpenTelemetry)

| Variable                      | Default                | Description                    |
|-------------------------------|------------------------|--------------------------------|
| `ENABLE_TRACING`              | `true`                 | Enable distributed tracing     |
| `TRACING_SERVICE_NAME`        | `integr8scode-backend` | Service name for traces        |
| `TRACING_SERVICE_VERSION`     | `1.0.0`                | Service version                |
| `TRACING_SAMPLING_RATE`       | `0.1`                  | Sampling rate (0.0 to 1.0)     |
| `TRACING_ADAPTIVE_SAMPLING`   | `false`                | Enable adaptive sampling       |
| `JAEGER_AGENT_HOST`           | `jaeger`               | Jaeger agent host              |
| `JAEGER_AGENT_PORT`           | `6831`                 | Jaeger agent UDP port          |
| `JAEGER_COLLECTOR_ENDPOINT`   | *none*                 | Jaeger HTTP collector URL      |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *none*                 | OTLP exporter endpoint         |
| `OTEL_SERVICE_NAME`           | *none*                 | OTLP service name override     |
| `OTEL_SERVICE_VERSION`        | *none*                 | OTLP version override          |
| `OTEL_RESOURCE_ATTRIBUTES`    | *none*                 | Additional resource attributes |

## Schema Configuration

| Variable             | Default            | Description             |
|----------------------|--------------------|-------------------------|
| `SCHEMA_BASE_PATH`   | `app/schemas_avro` | Base path for schemas   |
| `SCHEMA_AVRO_PATH`   | `app/schemas_avro` | Avro schema path        |
| `SCHEMA_CONFIG_PATH` | *none*             | Schema config file path |

## Development Configuration

| Variable           | Default | Description             |
|--------------------|---------|-------------------------|
| `TESTING`          | `false` | Enable test mode        |
| `DEVELOPMENT_MODE` | `false` | Enable development mode |
| `SECURE_COOKIES`   | `true`  | Require secure cookies  |
| `LOG_LEVEL`        | `DEBUG` | Logging level           |

## MongoDB Docker Configuration

These are used by Docker Compose for MongoDB initialization:

| Variable              | Default | Description           |
|-----------------------|---------|-----------------------|
| `MONGO_ROOT_USER`     | *none*  | MongoDB root username |
| `MONGO_ROOT_PASSWORD` | *none*  | MongoDB root password |

## Service Metadata

| Variable          | Default                | Description        |
|-------------------|------------------------|--------------------|
| `SERVICE_NAME`    | `integr8scode-backend` | Service identifier |
| `SERVICE_VERSION` | `1.0.0`                | Service version    |
