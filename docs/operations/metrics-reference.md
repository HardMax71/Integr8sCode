# Metrics Reference

The backend (API) and the worker both push their metrics over OTLP to the OpenTelemetry Collector every 60 seconds, and the collector writes them to VictoriaMetrics. Every resource attribute becomes a label, so a series carries `service_name` (`integr8scode-backend` or `integr8scode-worker`, from `SERVICE_NAME`), `job` (`integr8scode/<service_name>`) and a `service_instance_id` that the OTel SDK generates per process. Every table below says which process records a metric.

## Export path

```mermaid
flowchart LR
    API["backend"] -->|"OTLP gRPC, every 60 s"| Collector["otel-collector"]
    Worker["worker"] -->|"OTLP gRPC, every 60 s"| Collector
    Host["host-metrics (host network)"] -->|"OTLP gRPC to 127.0.0.1:4317"| Collector
    Receivers["mongodb, kafka_metrics receivers"] --> Collector
    Collector -->|"prometheus remote write"| VM["VictoriaMetrics"]
    VM -->|"scrapes span counters every 15 s"| Collector
    VM --> Grafana
```

`create_app` and the worker's `main()` each call `setup_metrics` (`app/core/metrics/base.py`) once. It installs a global `MeterProvider` whose `PeriodicExportingMetricReader` exports every 60 000 ms through an OTLP gRPC exporter. The exporter targets `OTEL_EXPORTER_OTLP_ENDPOINT`, which `config.toml` sets to `http://otel-collector:4317`. It also starts the system metrics instrumentation for the process's own CPU and memory. Without an endpoint it returns early and the no-op provider stays. The OpenTelemetry instrumentations take their meters from that provider. The app's own metrics have no meter at all: they come from spans, described next.

The collector's metrics pipeline (`backend/otel-collector-config.yaml`) reads the `otlp`, `kafka_metrics` and `mongodb` receivers, runs `memory_limiter`, `batch` and `resource`, and exports with `prometheus_remote_write` to `http://victoria-metrics:8428/api/v1/write`. VictoriaMetrics keeps 30 days. Host metrics come from a second collector, the `host-metrics` service (`backend/otel-host-metrics.yaml`). It runs only the `host_metrics` receiver in the host's network namespace, since in a container the network scraper sees only that container's `eth0` and `lo`, and sends to the main collector's OTLP port on `127.0.0.1:4317`. Both collectors, VictoriaMetrics and Grafana sit in the `observability` compose profile, so none of this runs unless you start the stack with `./deploy.sh dev --observability`. Counters and histograms made from spans take another way, described next.

## Metrics made from spans

Some metrics have no instrument in the code. A service puts the facts on a span, and the collector's `signaltometrics` connector (alpha in collector v0.162.0) turns them into counters, histograms and gauges, defined under `connectors` in `backend/otel-collector-config.yaml`. The SDK sends every span (`TRACING_SAMPLING_RATE = 1.0`), and the traces pipeline gives each span to the connector before `tail_sampling` decides what Jaeger keeps, so the counts don't depend on sampling. The connector emits a point only when a matching span arrives. Sent straight to VictoriaMetrics, a counter that sees one event every half hour would get one point every half hour, and `increase` and `rate` stop finding the previous point once two points are more than about 8 to 10 minutes apart (measured on v1.153.0): `increase` then counts the whole total again, and `rate` returns nothing. So counters and histograms go another way. `deltatocumulative` adds up the connector's deltas and keeps each total through 24 hours without spans (its default is 5 minutes, after which an idle counter would start again from zero). The collector's `prometheus` exporter serves the totals on `otel-collector:8889`, and VictoriaMetrics scrapes it every 15 seconds (`backend/victoria-metrics/scrape.yaml`, with `honor_labels` so each service's `job` and `instance` stay). A series the exporter hasn't updated for 24 hours drops out until its next span. Gauges still go by remote write, so a gauge goes stale when the job that reports it on a timer stops. Panels wrap counter rates in `or vector(0)` so a series that hasn't started yet reads 0. Every app metric works this way since [#389](https://github.com/HardMax71/Integr8sCode/issues/389).

## Names and labels in VictoriaMetrics

Code names instruments with dots, and they arrive with underscores. The collector's Prometheus translator also changes three things:

- It appends the unit: `s` becomes `_seconds`, `%` becomes `_percent`, `event/s` becomes `_event_per_second`, and `MiB` and `x` go on unchanged. Unit `1` adds `_ratio` to a gauge and nothing to a counter, and `{key}` adds nothing. A unit that is already a word of the name isn't repeated.
- Counters end in exactly one `_total`, so `sse.messages.sent.total` becomes `sse_messages_sent_total`.
- Histograms split into `_bucket`, `_sum` and `_count`. The tables list the name before those suffixes.

The contract test `backend/tests/contract/test_grafana_metrics.py` applies the same rule. It fails when a dashboard or alert queries a name nothing emits, and when code defines a metric that no dashboard uses.

Resource attributes become labels on every series: `job` (`integr8scode/integr8scode-backend`), `service_name`, `service_namespace`, `service_version`, `deployment_environment`, the `telemetry_sdk_*` set, and `instance` with `service_instance_id`, a fresh UUID each time the process starts. `otel_scope_name` names what made the series: an instrumentation such as `opentelemetry.instrumentation.fastapi`, or the collector's signaltometrics connector for every metric made from spans. Since `instance` changes on every restart, wrap queries in `sum` or `max` instead of reading single series.

Gauges listed as "in process" are up-down counters the process keeps itself. They start at zero when the process starts, whatever the real state is.

## Application metrics

### HTTP and process

The OpenTelemetry FastAPI instrumentation records HTTP in the backend, with the stable semantic convention names since the image sets `OTEL_SEMCONV_STABILITY_OPT_IN=http`. It skips health, metrics, docs and `openapi.json`. `http_route` is FastAPI's route template, such as `/api/v1/executions/{execution_id}`.

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `http_server_request_duration_seconds` | histogram | http_request_method, http_route, http_response_status_code, url_scheme, network_protocol_version | its `_count` is the request rate |
| `http_server_request_body_size_bytes` | histogram | as above | requests with a body |
| `http_server_response_body_size_bytes` | histogram | as above | |
| `http_server_active_requests` | gauge, in process | http_request_method, url_scheme | no route, so open SSE streams can't be told apart |

The system metrics instrumentation records each backend and worker process's own `process_memory_usage_bytes`, `process_memory_virtual_bytes`, `process_cpu_time_seconds_total` (type: user, system), `process_cpu_utilization`, `process_thread_count` and `process_open_file_descriptor_count`. `PROCESS_METRICS` in `app/core/metrics/base.py` picks them; the host's own figures come from the collector.

### Executions and queue

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `script_executions_total` | counter | execution_status, execution_lang_and_version | span `execution.submit` from `ExecutionService.execute_script` in backend (queued, error), and span `execution.result` from `ResultProcessor` in worker (completed, failed, timeout) |
| `script_errors_total` | counter | execution_error_type | the same spans when they carry `execution.error_type`: the publish exception's class at submission, the event's error type or `timeout` at the result |
| `script_execution_duration_seconds` | histogram | execution_lang_and_version | `execution.runtime_seconds` on `execution.result`: wall time from the pod's resource usage, or the timeout for timed out runs |
| `script_memory_usage_MiB` | histogram | execution_lang_and_version | `execution.memory_mib` on `execution.result` for completed runs: peak memory |
| `script_memory_utilization_percent` | histogram | execution_lang_and_version | `execution.memory_percent` on the same spans: peak memory over the effective memory limit for the language (admin setting or TOML, raised to the language minimum) |
| `queue_depth` | gauge | none | span `queue.schedule_pending` from the worker's scheduler job, every 10 s: pending executions in Redis |
| `queue_active` | gauge | none | the same span: running slots in Redis |
| `queue_enqueue_total` | counter | none | span `queue.enqueue` from `ExecutionQueueService.enqueue` in worker |
| `queue_schedule_total` | counter | none | span `queue.schedule` with `queue.outcome` `scheduled` |
| `queue_wait_time_seconds` | histogram | queue_priority | `queue.wait_seconds` on those spans: enqueue to schedule |
| `queue_event_data_lost_total` | counter | none | span `queue.schedule` with `queue.outcome` `event_data_lost`: the queued event had expired in Redis |

All of these come from spans (see [Metrics made from spans](#metrics-made-from-spans)). Both queue gauges read Redis on each run of the job, so they stay right across worker restarts. The execution dashboard's submission latency reads `http_server_request_duration_seconds` for the execute and retry routes.

### Events and idempotency

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `events_published_total` | counter | event_type | span `publish_event` from `UnifiedProducer.produce` without an error status: the event was stored and published, in every process that publishes |
| `event_processing_duration_seconds` | histogram | event_type | the length of those spans: persisting the event and publishing it |
| `idempotency_cache_hits_total` | counter | idempotency_event_type, idempotency_operation | span `idempotency.check` with `idempotency.result` `hit` |
| `idempotency_cache_misses_total` | counter | idempotency_event_type, idempotency_operation | the same span with `idempotency.result` `miss` |
| `idempotency_duplicates_blocked_total` | counter | idempotency_event_type | span `idempotency.duplicate_blocked`, when the key is already completed or still processing |
| `idempotency_check_duration_seconds` | histogram | idempotency_operation | the length of `idempotency.check` |
| `idempotency_processing_duration_seconds` | histogram | idempotency_event_type, idempotency_status | `idempotency.processing_seconds` on span `idempotency.processed`: reserving the key to marking it completed or failed |
| `idempotency_keys_active` | gauge | none | span `idempotency.keys` from the worker's job every 30 s, which counts `idempotency:*` in Redis with `SCAN` |

Every Kafka publish also shows up in `messaging_publish_messages_message_total`; a publish that fails is marked on the stored event and not counted here. A handler that raises has no counter of its own: it's a `messaging_process_duration_seconds` sample with an `error_type` label, in the FastStream families below. `IdempotencyManager` runs in backend for `Idempotency-Key` requests and in the worker's execution scheduler consumer.

### Server-sent events (backend)

`SSERedisBus.listen_execution`, `listen_notifications` and `listen_replay`.

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `sse_connections_active` | gauge | sse_endpoint: executions, notifications, replay | span `sse.streams`, one per endpoint with zeros, from the API's job every 10 s: the streams that process has open |
| `sse_connection_duration_seconds` | histogram | sse_endpoint | `sse.duration_seconds` on span `sse.stream_closed`, when the stream closes |
| `sse_messages_sent_total` | counter | sse_endpoint, sse_event_type | span `sse.message` for each message relayed from Redis; the event type is the execution event type, `notification` or `replay_status` |

The status snapshot a stream sends first comes from the database, not Redis, and isn't counted.

### Kubernetes pods

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `pod_creations_total` | counter | pod_creation_result: success, failed; pod_language | span `pod.create` from `KubernetesWorker` in worker |
| `pod_creation_duration_seconds` | histogram | pod_language | the length of `pod.create` for successful creations: ConfigMap, pod and `PodCreated` publish |
| `pod_creations_active` | gauge | none | `pod.active_creations` on `pod.create`, reported as each creation ends |
| `configmaps_created_total` | counter | pod_configmap_result: success, already_exists, failed | span `pod.create_configmap` |
| `pods_by_phase` | gauge | pod_phase | span `pod_monitor.pods`, one per phase with zeros included, at the end of each `PodMonitor.watch_cycle` in worker (at most 35 s apart): executor pods seen through LIST and watch; a relist rebuilds the counts |
| `pod_lifetime_seconds` | histogram | pod_phase, pod_language | `pod.lifetime_seconds` on `pod_monitor.event` for the event that finished the execution: pod creation to that event |
| `pod_monitor_events_total` | counter | pod_monitor_watch_event, pod_phase | `pod_monitor.published` on span `pod_monitor.event`: the application events one watch event produced |
| `pod_monitor_processing_duration_seconds` | histogram | pod_monitor_watch_event: ADDED, MODIFIED, DELETED | the length of `pod_monitor.event`: mapping and publishing one watch event |
| `pod_monitor_reconciliations_total` | counter | none | span `pod_monitor.list`: each full LIST, on start and after 410 Gone |
| `pod_monitor_watch_errors_total` | counter | pod_monitor_error_type: resource_version_expired, api_error, unexpected, processing_error | `pod_monitor.watch` and `pod_monitor.event` spans that carry `pod_monitor.error_type` |
| `pod_monitor_watch_reconnects_total` | counter | none | `pod_monitor.watch` spans that carry `pod_monitor.error_type` |

### Notifications (backend)

`NotificationService` in backend. Each delivery is a `notification.deliver` span, and the throttle and each retry leave a span named `notification.throttled` or `notification.retry`. `notification_category` is the notification's first tag, such as `execution`, or `unknown` without tags.

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `notifications_sent_total` | counter | notification_category | `notification.deliver` with `notification.result` `delivered` |
| `notifications_by_severity_total` | counter | notification_severity, notification_category | the same spans, by severity |
| `notification_delivery_time_seconds` | histogram | notification_category | `notification.delivery_seconds` on those spans: delivery attempts including backoff waits |
| `notifications_failed_total` | counter | notification_category, notification_error | `notification.deliver` with `notification.result` `failed`; the error is the exception type of the last attempt |
| `notification_retries_total` | counter | notification_category | `notification.retry`: each failed attempt that backoff retries |
| `notifications_throttled_total` | counter | notification_category: general | `notification.throttled`: the per-user throttle |

### Event replay (worker)

`EventReplayService` runs in the worker. The admin route counts a session when it schedules it, and the worker's job reports the stored sessions per status every 10 seconds for the gauge.

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `replay_sessions_created_total` | counter | none | span `replay.session_created`, from the API when it schedules a session |
| `replay_sessions_by_status` | gauge | replay_status | span `replay.sessions`, one per status with zeros, every 10 s: the sessions in `replay_sessions` |
| `replay_status_changes_total` | counter | replay_from_status, replay_to_status | span `replay.status_change` |
| `replay_events_processed_total` | counter | replay_event_type | span `replay.event` with `replay.result` `replayed` |
| `replay_events_failed_total` | counter | replay_event_type | the same span with `replay.result` `failed` |
| `replay_event_processing_time_seconds` | histogram | replay_event_type | `replay.processing_seconds` on `replay.event`: sending one event |
| `replay_duration_seconds` | histogram | none | span `replay.session_completed`, completed sessions only |
| `replay_throughput_event_per_second` | histogram | none | events over duration on the same span |
| `replay_batch_size` | histogram | none | span `replay.batch` |

### Authentication and authorization (backend)

Each login runs in an `auth.login` span; the other events leave a span named in the table where the code used to record the metric.

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `authentication_attempts_total` | counter | auth_method, auth_success | span `auth.login` from `AuthService.login`; the method is `login` |
| `authentication_failures_total` | counter | auth_method | the same span with `auth.success` false |
| `authentication_duration_seconds` | histogram | auth_method | the length of that span |
| `accounts_locked_total` | counter | auth_reason: brute_force | span `auth.account_locked`, when a failed login triggers the lockout |
| `brute_force_attempts_total` | counter | none | span `auth.locked_login`, a login against an account that is already locked |
| `weak_password_attempts_total` | counter | auth_weakness_type: too_short | span `auth.weak_password` from `AuthService.register` |
| `token_validation_failures_total` | counter | auth_reason: expired, invalid_signature, invalid, missing_subject | span `auth.token_rejected` from `SecurityService.decode_token` |
| `csrf_validation_failures_total` | counter | auth_reason: missing_header, token_mismatch, invalid_signature | span `auth.csrf_rejected` from `SecurityService.validate_csrf_from_request` |
| `authorization_checks_total` | counter | auth_resource, auth_action, auth_allowed, auth_user_role | span `auth.authorization` from `AuthService.get_admin`, on every admin route |
| `authorization_denials_total` | counter | auth_resource, auth_action, auth_user_role | the same span with `auth.allowed` false |
| `password_reset_requests_total` | counter | auth_method: admin | span `auth.password_reset` from `AdminUserService` |

### Rate limiting (backend)

`RateLimitService.check_rate_limit`, called from `RateLimitMiddleware`, leaves a `rate_limit.request` span for each check and a `rate_limit.decision` span when a rule applies. `rate_limit_endpoint` is the path with UUIDs and any segment of 20 or more letters and digits replaced by `*`. Shorter IDs such as `/42` stay as they are.

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `rate_limit_requests_total` | counter | rate_limit_endpoint, rate_limit_authenticated, rate_limit_algorithm | `rate_limit.request`: the matched rule's algorithm, or `bypassed`, `no_limit` and `redis_error` |
| `rate_limit_allowed_total` | counter | rate_limit_endpoint, rate_limit_group | `rate_limit.decision` with `rate_limit.allowed` true |
| `rate_limit_rejected_total` | counter | rate_limit_endpoint, rate_limit_group | the same span with `rate_limit.allowed` false |
| `rate_limit_bypass_total` | counter | rate_limit_endpoint | `rate_limit.request` with algorithm `bypassed`: users with `bypass_rate_limit` |

### Dead letter queue

`DLQManager` puts each step on a span. `handle_message` runs wherever a router's `DeadLetterMiddleware` catches a failure: the backend for notifications, and the execution scheduler's group in the worker. Scheduled retries and the size report run from the worker's APScheduler job every 10 seconds.

| Metric | Type | Labels | Recorded from |
|--------|------|--------|---------------|
| `dlq_messages_received_total` | counter | dlq_original_topic, dlq_event_type | span `dlq.handle` with `dlq.outcome` `stored` |
| `dlq_message_age_seconds` | histogram | none | `dlq.message_age_seconds` on those spans: from the failure to the save |
| `dlq_messages_retried_total` | counter | dlq_original_topic, dlq_event_type, dlq_retry_result: success, failed | span `dlq.retry` |
| `dlq_processing_errors_total` | counter | dlq_original_topic, dlq_event_type, dlq_error_type | span `dlq.retry` with `dlq.retry_result` `failed`; the error type is the publish exception's class |
| `dlq_messages_discarded_total` | counter | dlq_original_topic, dlq_event_type, dlq_discard_reason | span `dlq.discard` |
| `dlq_processing_duration_seconds` | histogram | dlq_operation: handle, retry, discard | the length of those three spans |
| `dlq_queue_size` | gauge | dlq_original_topic | span `dlq.queue_size` from the scheduled job, one per topic with pending or scheduled rows |

A `handle` span contains the discard or immediate retry it starts, so its duration includes them. A topic with no pending or scheduled rows gets no `dlq.queue_size` span, so its gauge stops getting points.

## FastStream messaging families

`BrokerProvider` puts FastStream's `KafkaTelemetryMiddleware` on every broker, so both processes record these.

| Metric | Type | Labels |
|--------|------|--------|
| `messaging_publish_messages_message_total` | counter | messaging_system, messaging_destination_name |
| `messaging_publish_duration_seconds` | histogram | messaging_system, messaging_destination_name, error_type on failure |
| `messaging_process_messages_message_total` | counter | messaging_system, messaging_destination_publish_name |
| `messaging_process_duration_seconds` | histogram | messaging_system, messaging_destination_publish_name, error_type on failure |

`messaging_system` is `kafka`. Both topic labels hold the topic name: the publish side calls it `messaging_destination_name`, the consume side `messaging_destination_publish_name`.

## Collector families the dashboards use

Collector receivers write these, not Python, so the contract test accepts them by prefix (`COLLECTOR_PREFIXES`).

`system_memory_utilization_ratio{state}` comes from the host-metrics collector's memory scraper with `system.memory.utilization` turned on. The overview's "Memory Saturation" gauge and both host memory alert rules read it. The HTTP dashboard's "CPU" panel reads `system_cpu_utilization_ratio{state}`, from the cpu scraper with `system.cpu.utilization` turned on, and "Host Memory Used" reads `system_memory_usage_bytes{state="used"}`. Below them, "Load Average" reads `system_cpu_load_average_{1m,5m,15m}` from the load scraper next to `system_cpu_logical_count`, and "Disk I/O" reads `system_disk_io_bytes_total{device,direction}` from the disk scraper for whole disks only (`sd*`, `vd*`, `xvd*`, `nvme*n*`), since partitions would count the same bytes twice. "Network I/O" reads `system_network_io_bytes_total{device,direction}` for the host's interfaces; host-metrics leaves out `lo` and the per-container `veth*` pairs, whose traffic also crosses a bridge and the NIC. "Disk Space Used" divides `system_filesystem_usage_bytes{state="used"}` by used plus free per mountpoint, the way `df` counts it.

The `mongodb` receiver polls `mongo:27017` every 15 seconds as `MONGO_MONITOR_USER`. Several of these are optional receiver metrics that `otel-collector-config.yaml` turns on. The MongoDB dashboard reads:

| Area | Families |
|------|----------|
| Server | `mongodb_health_ratio`, `mongodb_uptime_milliseconds_total`, `mongodb_session_count`, `mongodb_cursor_count`, `mongodb_cursor_timeout_count`, `mongodb_database_count` |
| Load | `mongodb_active_reads`, `mongodb_active_writes`, `mongodb_operation_latency_time_microseconds`, `mongodb_{commands,queries,inserts,updates,deletes,getmores,flushes}_rate_per_second` |
| Storage, by `db_namespace` | `mongodb_data_size_bytes`, `mongodb_storage_size_bytes_total`, `mongodb_index_size_bytes`, `mongodb_object_count`, `mongodb_collection_count`, `mongodb_index_count`, `mongodb_index_access_count` |
| Memory and cache | `mongodb_memory_usage_bytes`, `mongodb_cache_operations_total` (type hit or miss), `mongodb_page_faults_total`, `mongodb_wtcache_bytes_read_total` |
| Network and locks | `mongodb_network_io_receive_bytes`, `mongodb_network_io_transmit_bytes`, `mongodb_network_request_count`, `mongodb_global_lock_time_milliseconds_total`, `mongodb_lock_acquire_count_total`, `mongodb_lock_acquire_wait_count_total` |

Five of these are counts since mongod started that the receiver declares as non-monotonic sums, so they arrive as gauges: `mongodb_cursor_timeout_count`, `mongodb_network_io_receive_bytes`, `mongodb_network_io_transmit_bytes`, `mongodb_network_request_count` and `mongodb_index_access_count`. They only grow, so their panels take `rate()` of them, and a mongod restart reads as a counter reset.

The `kafka_metrics` receiver's consumers scraper gives `kafka_consumer_group_lag_sum_ratio{group,topic}`, the messages a consumer group has yet to read on a topic. The Kafka dashboard's "Consumer Lag by Group" panel reads it. The receiver gives it unit `1`, so the name ends in `_ratio`. "Consumer Group Members" reads `kafka_consumer_group_members{group}`, and a group at 0 has nobody reading its topics. A group the code no longer uses stays at 0 until Kafka drops its offsets, 7 days after its last member left (`offsets.retention.minutes`).

The MongoDB dashboard's "Connections" panel reads `mongodb_connection_count{type}` for `current` and `active`; `available` is left out, since it sits in the hundreds of thousands.

Everything else the receivers collect lands in VictoriaMetrics with no panel, and Grafana's Explore view can query it: the other `kafka_*` broker, topic, partition and consumer group families, `mongodb_operation_count_total`, `mongodb_operation_time_milliseconds_total` and `mongodb_document_operation_count`, the rest of the cpu, disk, filesystem and network scrapers, and the paging and processes scrapers. host-metrics mounts only the host's `/proc` and `/sys`, so the filesystem scraper reports only `/`, the disk its container's overlay sits on.

## PromQL examples

These work against what backend exports today.

```promql
# p95 execution time by runtime
histogram_quantile(0.95, sum by (le, execution_lang_and_version) (rate(script_execution_duration_seconds_bucket[5m])))

# share of API requests answered with a 5xx
sum(rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[5m])) / sum(rate(http_server_request_duration_seconds_count[5m]))

# share of rate limit checks rejected
sum(rate(rate_limit_rejected_total[5m])) / sum(rate(rate_limit_requests_total[5m]))

# Kafka messages published per topic, per second
sum by (messaging_destination_name) (rate(messaging_publish_messages_message_total[5m]))

# rejected access tokens by reason
sum by (auth_reason) (rate(token_validation_failures_total[5m]))

# MongoDB cache hit ratio
sum(rate(mongodb_cache_operations_total{type="hit"}[5m])) / sum(rate(mongodb_cache_operations_total[5m]))
```

`sum(pods_by_phase{pod_phase="Pending"})` shows executor pods waiting for a node or an image pull.
