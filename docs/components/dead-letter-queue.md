# Dead letter queue

When a Kafka handler raises, its event goes to the dead letter queue, and the dlq-processor later sends it back to the one consumer group that failed. The queue is the `dlq_messages` MongoDB collection, not a Kafka topic. FastStream has no dead letter queue for Kafka, so two small middlewares in `app/events/middlewares.py` connect the subscribers to it.

## What happens to a failed event

Every subscriber except the SSE bridge uses `AckPolicy.ACK`, which commits the offset after the handler returns, whether it succeeded or raised. The k8s worker, result processor, saga orchestrator and notification routers also carry `DeadLetterMiddleware`:

```python
--8<-- "backend/app/events/middlewares.py:DeadLetterMiddleware"
```

When the handler raises, the middleware passes the event to `DLQManager.handle_message` with its topic, the subscriber's consumer group, the error and the retry count, then re-raises. FastStream logs the error, the telemetry middleware counts it in `messaging_process_duration_seconds` under `error_type`, and the offset is committed. Where the router also has an idempotency guard, the guard releases the event's key on the way out, so the retry isn't turned away as a duplicate.

`handle_message` drops the message if it's older than 7 days or its event id starts with `test-` (outside the test environment). Otherwise it saves the row as `pending`, publishes `dlq_message_received`, and then either discards the message, when its retries are used up, or schedules the next retry by the event type's policy.

The SSE bridge has no DLQ middleware. It acks before it runs (`ACK_FIRST`), and pushing a stale status to a browser minutes later would do more harm than missing it.

## Retries

The [DLQ processor](workers/dlq_processor.md) runs every 10 seconds. It picks up rows with status `scheduled` whose `next_retry_at` has passed, marks each one `retried` with its retry count plus one, and republishes the event to its original topic.

Every consumer group on that topic receives the retried event, so the publish carries two headers: `x-dlq-consumer-group` names the group that failed and `x-dlq-retry-count` the attempt. `RetryTargetMiddleware`, which every broker has, makes the other groups skip it. If the retry fails again, `DeadLetterMiddleware` saves it with that retry count, so the same row goes back to `pending` and gets scheduled or discarded. A retry that succeeds leaves the row at `retried`. If the republish itself fails, the row goes back to `scheduled` and the next cycle tries again.

The row is marked before the publish on purpose. A retry can fail and save its new failure within milliseconds, and marking afterwards would overwrite that with `retried`.

Retry policies are hardcoded in `app/dlq/models.py`, chosen by event type:

| Event types | Strategy | Max retries | Base delay | Max delay |
|-------------|----------|-------------|------------|-----------|
| Execution events and commands | Exponential, x2 | 5 | 30 s | 300 s |
| Pod events | Exponential, x3 | 3 | 60 s | 600 s |
| `result_stored`, `result_failed` | Immediate | 3 | | |
| Everything else | Exponential, x2.5 | 4 | 60 s | 1800 s |

Exponential delays get 10% jitter. A message whose `retry_count` has reached the limit is discarded with reason `max_retries_exceeded`, and `dlq_message_discarded` goes out.

## Storage

A row is one event in one consumer group. The unique index is on `event.event_id` plus `consumer_group`, so when the saga orchestrator and the result processor both fail on the same `execution_completed`, each gets its own row and its own retry. A TTL index deletes rows 7 days after `created_at`.

A database created before consumer groups were added still has the old unique index `idx_dlq_event_id` on `event.event_id` alone, and Beanie never drops indexes. Until someone runs `db.dlq_messages.dropIndex("idx_dlq_event_id")` once, a second group that fails on the same event can't save its row.

The `DLQ_*` keys in config.toml (`DLQ_RETRY_MAX_ATTEMPTS`, `DLQ_RETRY_BASE_DELAY_SECONDS`, `DLQ_RETRY_MAX_DELAY_SECONDS`, `DLQ_RETENTION_DAYS`, `DLQ_WARNING_THRESHOLD`, `DLQ_CRITICAL_THRESHOLD`) are loaded and validated by `Settings`, but no code uses them ([#293](https://github.com/HardMax71/Integr8sCode/issues/293)). There's no HTTP API for the DLQ.

## Key files

| File | Purpose |
|------|---------|
| [`middlewares.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/events/middlewares.py) | `DeadLetterMiddleware` and `RetryTargetMiddleware` |
| [`manager.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/dlq/manager.py) | Intake, retry, discard |
| [`models.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/dlq/models.py) | Statuses, retry policies and the two headers |
| [`dlq.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/docs/dlq.py) | `dlq_messages` document and indexes |
| [`run_dlq_processor.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/workers/run_dlq_processor.py) | Worker entry point |
