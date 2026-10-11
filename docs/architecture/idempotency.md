# Idempotency

Kafka delivers at least once, so a consumer can see the same event twice. Handlers that must not run twice go through `IdempotencyManager`, which keeps one Redis key per event and lets only the first caller through. The API reuses the same manager for the `Idempotency-Key` header on `POST /api/v1/execute`.

## Who uses it

| Caller | Events | Key strategy | TTL |
|--------|--------|--------------|-----|
| Saga orchestrator | `execution_requested`, `execution_completed`, `execution_failed`, `execution_timeout`, `execution_cancelled` | `EVENT_BASED` | 1 hour |
| K8s worker | `create_pod_command`, `delete_pod_command` | `CONTENT_HASH` | 1 hour |
| Result processor | `execution_completed`, `execution_failed`, `execution_timeout` | `CONTENT_HASH` | 2 hours |
| API, `POST /api/v1/execute` with `Idempotency-Key` | none, see below | `CUSTOM` | 24 hours |

The other subscribers, `sse-bridge-pool` and `notification-service`, don't use it. The subscriptions live in `backend/app/events/handlers.py`, one `KafkaRouter` per consumer, and the guard is a middleware on the router, so it covers every subscriber on it.

Keys aren't scoped by consumer group. The saga orchestrator and the result processor both guard `execution_completed`, `execution_failed` and `execution_timeout`, and they only stay out of each other's way because one keys on the event id and the other on a content hash. Two routers with the same strategy on the same event would skip each other's deliveries.

## Keys

The manager builds a key from the event in one of three ways:

```python
--8<-- "backend/app/services/idempotency/idempotency_manager.py:generate_key"
```

`EVENT_BASED` is `{event_type}:{event_id}` and is the default when a caller passes no strategy. `CONTENT_HASH` is a SHA-256 of the event JSON with `event_id`, `timestamp` and `metadata` removed, so an event published twice under two different ids still counts as one. `CUSTOM` is `{event_type}:{custom_key}` with a key the caller picks. Every key gets the `idempotency:` prefix.

## How a check works

```mermaid
flowchart TB
    IN[Event] --> GET{Key in Redis?}
    GET -->|No| NX[SET NX EX: processing]
    NX -->|Won| RUN[Run handler]
    NX -->|Lost the race| GET
    GET -->|completed or failed| DUP[Duplicate, skip]
    GET -->|processing| AGE{Older than 300 s?}
    AGE -->|No| DUP
    AGE -->|Yes| RUN
    RUN -->|OK| DONE[Mark completed]
    RUN -->|Raises| FAIL[Mark failed, re-raise]
```

A record has one of three states:

```python
--8<-- "backend/app/domain/idempotency/models.py:IdempotencyStatus"
```

`check_and_reserve` reads the key first. If it's missing, the manager writes a `processing` record with `SET NX EX`, so of two racing consumers only one wins. The loser reads the key again and gets treated as a duplicate.

```python
--8<-- "backend/app/services/idempotency/redis_repository.py:insert_processing"
```

When `SET NX` loses, the repository raises pymongo's `DuplicateKeyError`, odd for a Redis store but it's what the manager catches. Each record is a JSON document with the status, the event type and id, timestamps, processing duration, the error and an optional cached result. Updates keep the key's remaining TTL, read with `TTL` in whole seconds. If that reads 0 because the key is about to expire, the rewrite sets no expiry at all and the key stays until something deletes it.

A `processing` record older than `processing_timeout_seconds` (300) is taken to be a crashed consumer. The manager resets its `created_at` and lets the new caller run. `completed` and `failed` records both count as duplicates until the key expires.

Kafka handlers get the guard from `IdempotencyMiddleware`, which each router takes with its key strategy and TTL:

```python
--8<-- "backend/app/events/middlewares.py:IdempotencyMiddleware"
```

It runs before FastStream hands the message to the handler, so it parses the raw body into the `DomainEvent` union itself and takes the manager from the request container that the broker's Dishka middleware opens around it.

A duplicate is logged and skipped, and the message is acked as usual. A handler that raises leaves a `failed` record, which blocks that event for the rest of the TTL, so this layer never retries a failure. Nothing else retries it either today: see [issue #288](https://github.com/HardMax71/Integr8sCode/issues/288).

## HTTP Idempotency-Key

`POST /api/v1/execute` takes an optional `Idempotency-Key` header. Without it the request runs as usual. With it, `ExecutionService.execute_script_idempotent` reserves the custom key `http:{user_id}:{key}` for 24 hours, so two users can reuse the same header value without clashing. The Redis key ends up as `idempotency:execution_requested:http:{user_id}:{key}`.

On success the manager stores the new execution as JSON in the record. A repeat with the same key gets one of these:

| Repeat request arrives | Response |
|------------------------|----------|
| After the first one succeeded | 200 with the cached execution, same `execution_id`, nothing new runs |
| While the first one is still running | 409, "Duplicate request '<key>' is still being processed" |
| After the first one failed | Runs again, since a failed request deletes its key |
| After the cached result went missing | 409, "Cached result for '<key>' is no longer available" |

A client that hits an error can retry with the same key.

## Configuration

```python
--8<-- "backend/app/services/idempotency/idempotency_manager.py:IdempotencyConfig"
```

The DI provider builds `IdempotencyConfig()` with these defaults; nothing in `config.toml` changes them. Every caller passes its own TTL, so `default_ttl_seconds` only applies to a caller that doesn't. Result caching is used by the HTTP path only. Event handlers mark keys completed without a result, and a result over `max_result_size_bytes` is logged and not stored.

## Metrics

`IdempotencyMetrics` in `backend/app/core/metrics/database.py` defines these. The second column is the series name in VictoriaMetrics after the collector's Prometheus conversion.

| Instrument | Series | Meaning |
|------------|--------|---------|
| `idempotency.cache.hits.total` | `idempotency_cache_hits_total` | Lookups that found a record, by `event_type` and `operation` |
| `idempotency.cache.misses.total` | `idempotency_cache_misses_total` | Lookups that found no record and went on to `SET NX`, whether or not they won it |
| `idempotency.duplicates.blocked.total` | `idempotency_duplicates_blocked_total` | Calls rejected as duplicates, by `event_type` |
| `idempotency.check.duration` | `idempotency_check_duration_seconds` | Histogram of `check_and_reserve` time |
| `idempotency.processing.duration` | `idempotency_processing_duration_seconds` | Histogram of reserve to completed or failed, by `event_type` and `status` |
| `idempotency.keys.active` | `idempotency_keys_active` | Observable gauge: `SCAN` count of `idempotency:*` keys in Redis at each export |
