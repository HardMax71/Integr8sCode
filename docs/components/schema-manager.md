# MongoDB indexes and TTLs

There's no schema manager or migration step. Each Beanie document declares its own indexes, either as `Indexed(...)` fields or in `Settings.indexes`, and every process creates them at startup: the API in its lifespan and each worker in its entry point call `init_beanie` with `ALL_DOCUMENTS` from `app/db/docs/__init__.py`. Beanie sends every declared index to `create_indexes` on each boot, which MongoDB treats as a no-op for an index that already exists with the same spec. Repositories never create indexes.

Beanie runs with index dropping off, so an index removed from a document stays in the database until someone drops it. Changing the options of an existing index makes MongoDB reject the create, and the process fails at startup. Drop the old index in mongosh first, then restart.

## TTLs

Three collections expire documents on their own:

| Collection | Expires |
|------------|---------|
| `events` | at `ttl_expires_at`, which `EventDocument` sets to 30 days after the event is created |
| `notifications` | 30 days after `created_at` |
| `dlq_messages` | 7 days after `created_at` |

The 30 days for events is hardcoded in the document. `EVENT_RETENTION_DAYS` in config.toml is never read ([#293](https://github.com/HardMax71/Integr8sCode/issues/293)). Everything else stays until something deletes it. That includes `executions`, `sagas` and `resource_allocations`. The event replay worker deletes finished `replay_sessions` older than 48 hours.

## Unique indexes the code relies on

| Collection | Unique on | Why |
|------------|-----------|-----|
| `sagas` | `execution_id` + `saga_name` | One saga of each name per execution; `get_or_create_saga` upserts on it |
| `events` | `event_id` | The producer stores before publishing and skips a duplicate id, so a replayed event isn't stored twice |
| `dlq_messages` | `event.event_id` + `consumer_group` | One DLQ row per event and consumer group |
| `notification_subscriptions` | `user_id` + `channel` | One subscription per channel |
| `users` | `username`, `email`, `user_id` | Registration conflicts become 409 |
| `user_settings` | `user_id` | One settings document per user |
| `system_settings` | `settings_id` | One `global` document; every read upserts it on this key |
| `events_archive` | `event_id` | A retried admin delete upserts the same archive row |

`executions.execution_id`, `saved_scripts.script_id`, `sagas.saga_id`, `resource_allocations.allocation_id`, `replay_sessions.session_id`, `audit_log.audit_id` and `notifications.notification_id` are unique as well.

Idempotency keys, the execution queue and the SSE channels live in Redis, not MongoDB.

## Key files

| File | Purpose |
|------|---------|
| [`docs/__init__.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/docs/__init__.py) | `ALL_DOCUMENTS` |
| [`event.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/docs/event.py) | `events` indexes and TTL |
| [`dishka_lifespan.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/dishka_lifespan.py) | `init_beanie` in the API |
