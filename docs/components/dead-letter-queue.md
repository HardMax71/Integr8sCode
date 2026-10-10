# Dead letter queue

Nothing feeds the dead letter queue today, so a Kafka event whose handler fails is lost. [#288](https://github.com/HardMax71/Integr8sCode/issues/288) tracks the fix. This page describes what the code does now.

## What happens to a failed event

Every subscriber in `app/events/handlers.py` uses `AckPolicy.ACK`, which commits the offset after the handler returns, whether it succeeded or raised. A handler that raises is logged and counted in the `event.processing.errors.total` metric. Where the handler has an idempotency guard, its key is marked failed, which would also turn away a redelivery while the key lives. Kafka doesn't redeliver it anyway, and nothing stores it for a retry. The SSE bridge uses `ACK_FIRST` and acks before it even runs.

`DLQManager.handle_message` in `app/dlq/manager.py` is the code that would take a failed message in: drop it if it's older than 7 days or its event id starts with `test-` (outside the test environment), save it to MongoDB, publish `dlq_message_received`, and schedule a retry. It has had no caller since the switch to one topic per event type in commit 95389b4.

## What's still there

Messages would live in the `dlq_messages` collection, never in a Kafka topic. The collection has a unique index on `event.event_id` and a TTL index that deletes rows 7 days after `created_at`.

The [DLQ processor](workers/dlq_processor.md) worker runs every 10 seconds, picks up rows with status `scheduled` whose `next_retry_at` has passed, republishes each event to its original topic and marks the row `retried`. Both `retried` and `discarded` are terminal, so a row is retried at most once and then stays `retried`, even if the retried event fails again. With nothing writing rows, every cycle finds nothing.

Retry policies are hardcoded in `app/dlq/models.py`, chosen by event type:

| Event types | Strategy | Max retries | Base delay | Max delay |
|-------------|----------|-------------|------------|-----------|
| Execution events and commands | Exponential, x2 | 5 | 30 s | 300 s |
| Pod events | Exponential, x3 | 3 | 60 s | 600 s |
| `result_stored`, `result_failed` | Immediate | 3 | | |
| Everything else | Exponential, x2.5 | 4 | 60 s | 1800 s |

Exponential delays get 10% jitter. At intake, a message whose `retry_count` has reached the limit is discarded with reason `max_retries_exceeded` and `dlq_message_discarded` is published.

The `DLQ_*` keys in config.toml (`DLQ_RETRY_MAX_ATTEMPTS`, `DLQ_RETRY_BASE_DELAY_SECONDS`, `DLQ_RETRY_MAX_DELAY_SECONDS`, `DLQ_RETENTION_DAYS`, `DLQ_WARNING_THRESHOLD`, `DLQ_CRITICAL_THRESHOLD`) are never read ([#293](https://github.com/HardMax71/Integr8sCode/issues/293)). There's no HTTP API for the DLQ either: the `/api/v1/dlq` routes were removed in the same commit.

## Key files

| File | Purpose |
|------|---------|
| [`manager.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/dlq/manager.py) | Intake, retry, discard |
| [`models.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/dlq/models.py) | Statuses and retry policies |
| [`dlq.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/docs/dlq.py) | `dlq_messages` document and indexes |
| [`run_dlq_processor.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/workers/run_dlq_processor.py) | Worker entry point |
