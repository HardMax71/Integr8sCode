# Metrics Reference

The platform exports metrics via OpenTelemetry to an OTLP-compatible collector (Jaeger, Prometheus, etc.). Each service
component has its own metrics class, and all metrics follow a consistent naming pattern: `{domain}.{metric}.{type}`.

## Architecture

Metrics are collected using the OpenTelemetry SDK and exported every 10 seconds to the configured OTLP endpoint:

```python
--8<-- "backend/app/core/metrics/base.py:init"
```

When `ENABLE_TRACING` is false or no OTLP endpoint is configured, the system uses a no-op meter provider to avoid
unnecessary overhead.

## Metric Categories

### Execution Metrics

Track script execution performance and resource usage.

| Metric                      | Type          | Labels                   | Description                  |
|-----------------------------|---------------|--------------------------|------------------------------|
| `script.executions.total`   | Counter       | status, lang_and_version | Total executions             |
| `script.execution.duration` | Histogram     | lang_and_version         | Execution time (seconds)     |
| `script.executions.active`  | UpDownCounter | -                        | Currently running executions |
| `script.memory.usage`       | Histogram     | lang_and_version         | Memory per execution (MiB)   |
| `script.cpu.utilization`    | Histogram     | -                        | CPU usage (millicores)       |
| `script.errors.total`       | Counter       | error_type               | Errors by type               |
| `execution.queue.depth`     | UpDownCounter | -                        | Queued executions            |
| `execution.queue.wait_time` | Histogram     | lang_and_version         | Queue wait time (seconds)    |

### Coordinator Metrics

Track scheduling and queue management.

| Metric                                   | Type          | Labels   | Description               |
|------------------------------------------|---------------|----------|---------------------------|
| `coordinator.scheduling.duration`        | Histogram     | -        | Scheduling time           |
| `coordinator.executions.active`          | UpDownCounter | -        | Active managed executions |
| `coordinator.queue.wait_time`            | Histogram     | priority | Queue wait by priority    |
| `coordinator.executions.scheduled.total` | Counter       | status   | Scheduled executions      |

### Rate Limit Metrics

Track rate-limiting behavior.

| Metric                           | Type      | Labels                             | Description               |
|----------------------------------|-----------|------------------------------------|---------------------------|
| `rate_limit.requests.total`      | Counter   | authenticated, endpoint, algorithm | Total checks              |
| `rate_limit.allowed.total`       | Counter   | group, priority, multiplier        | Allowed requests          |
| `rate_limit.rejected.total`      | Counter   | group, priority, multiplier        | Rejected requests         |
| `rate_limit.bypass.total`        | Counter   | endpoint                           | Bypassed checks           |
| `rate_limit.check.duration`      | Histogram | endpoint, authenticated            | Check duration (ms)       |
| `rate_limit.redis.duration`      | Histogram | operation                          | Redis operation time (ms) |
| `rate_limit.remaining`           | Histogram | -                                  | Remaining requests        |
| `rate_limit.quota.usage`         | Histogram | -                                  | Quota usage (%)           |
| `rate_limit.token_bucket.tokens` | Histogram | endpoint                           | Current tokens            |

### Event Metrics

Track Kafka event processing.

| Metric                       | Type          | Labels                 | Description       |
|------------------------------|---------------|------------------------|-------------------|
| `events.produced.total`      | Counter       | event_type, topic      | Events published  |
| `events.consumed.total`      | Counter       | event_type, topic      | Events consumed   |
| `events.processing.duration` | Histogram     | event_type             | Processing time   |
| `events.errors.total`        | Counter       | event_type, error_type | Processing errors |
| `events.lag`                 | UpDownCounter | topic, partition       | Consumer lag      |

### Database Metrics

Track MongoDB operations.

| Metric                        | Type          | Labels                | Description        |
|-------------------------------|---------------|-----------------------|--------------------|
| `database.operations.total`   | Counter       | operation, collection | Total operations   |
| `database.operation.duration` | Histogram     | operation, collection | Operation time     |
| `database.errors.total`       | Counter       | operation, error_type | Database errors    |
| `database.connections.active` | UpDownCounter | -                     | Active connections |

### Connection Metrics

Track SSE and WebSocket connections.

| Metric                      | Type          | Labels | Description              |
|-----------------------------|---------------|--------|--------------------------|
| `connections.active`        | UpDownCounter | type   | Active connections       |
| `connections.total`         | Counter       | type   | Total connections opened |
| `connections.duration`      | Histogram     | type   | Connection duration      |
| `connections.messages.sent` | Counter       | type   | Messages sent            |

### Health Metrics

Track service health.

| Metric                       | Type          | Labels          | Description              |
|------------------------------|---------------|-----------------|--------------------------|
| `health.checks.total`        | Counter       | service, status | Health check results     |
| `health.check.duration`      | Histogram     | service         | Check duration           |
| `health.dependencies.status` | UpDownCounter | dependency      | Dependency status (1=up) |

### Notification Metrics

Track notification delivery.

| Metric                            | Type      | Labels        | Description          |
|-----------------------------------|-----------|---------------|----------------------|
| `notifications.sent.total`        | Counter   | type, channel | Notifications sent   |
| `notifications.failed.total`      | Counter   | type, error   | Failed notifications |
| `notifications.delivery.duration` | Histogram | channel       | Delivery time        |

### Dead Letter Queue Metrics

Track DLQ operations.

| Metric               | Type          | Labels        | Description          |
|----------------------|---------------|---------------|----------------------|
| `dlq.messages.total` | Counter       | topic, reason | Messages sent to DLQ |
| `dlq.retries.total`  | Counter       | topic         | Retry attempts       |
| `dlq.size`           | UpDownCounter | topic         | Current DLQ size     |

## Configuration

Metrics are configured via environment variables:

| Variable                      | Default                | Description             |
|-------------------------------|------------------------|-------------------------|
| `ENABLE_TRACING`              | `true`                 | Enable metrics/tracing  |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | -                      | OTLP collector endpoint |
| `TRACING_SERVICE_NAME`        | `integr8scode-backend` | Service name in traces  |

## Prometheus Queries

Example PromQL queries for common dashboards:

```promql
# Execution success rate (last 5 minutes)
sum(rate(script_executions_total{status="completed"}[5m])) /
sum(rate(script_executions_total[5m]))

# P99 execution duration by language
histogram_quantile(0.99, sum(rate(script_execution_duration_bucket[5m])) by (le, lang_and_version))

# Rate limit rejection rate
sum(rate(rate_limit_rejected_total[5m])) /
sum(rate(rate_limit_requests_total[5m]))

# Queue depth trend
avg_over_time(execution_queue_depth[1h])
```

## Key Files

| File                                                                                                                         | Purpose                              |
|------------------------------------------------------------------------------------------------------------------------------|--------------------------------------|
| [`core/metrics/base.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/metrics/base.py)               | Base metrics class and configuration |
| [`core/metrics/execution.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/metrics/execution.py)     | Execution metrics                    |
| [`core/metrics/coordinator.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/metrics/coordinator.py) | Coordinator metrics                  |
| [`core/metrics/rate_limit.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/metrics/rate_limit.py)   | Rate limit metrics                   |
| [`core/metrics/`](https://github.com/HardMax71/Integr8sCode/tree/main/backend/app/core/metrics)                              | All metrics modules                  |
