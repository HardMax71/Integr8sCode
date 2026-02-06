# Schema management

The backend manages MongoDB collection schemas — indexes, validators, and TTL policies. These are initialized at process start, whether the process is the main API or a standalone worker.

Kafka event serialization is handled entirely by FastStream with Pydantic JSON; there is no schema registry involved. See [Event System Design](../architecture/event-system-design.md) for details on event serialization.

## MongoDB schema

The `SchemaManager` class in `app/db/schema/schema_manager.py` applies idempotent, versioned migrations to MongoDB. Each migration is a short async function that creates indexes or sets collection validators. The class tracks which migrations have run in a `schema_versions` collection, storing the migration id, description, and timestamp.

When `apply_all()` is called, it walks through an ordered list of migrations and skips any that already have a record in `schema_versions`. If the migration hasn't been applied, it runs the function and then marks it done. This design means you can safely call `apply_all()` on every startup without worrying about duplicate work — MongoDB's `create_indexes` is a no-op when indexes with matching names and specs already exist.

The system currently has nine migrations covering the main collections. The events collection gets the most attention: a unique index on `event_id`, compound indexes for queries by event type, aggregate, user, service, and status, a TTL index for automatic expiration, and a text search index across several fields. It also has a JSON schema validator set to moderate/warn mode, meaning MongoDB logs validation failures but doesn't reject writes.

Other migrations create indexes for user settings snapshots, replay sessions, notifications and notification rules, idempotency keys (with a one-hour TTL), sagas, execution results, and DLQ messages (with a seven-day TTL). The idempotency and DLQ TTL indexes automatically clean up old documents without manual intervention.

Repositories don't create their own indexes — they only read and write. This separation keeps startup behavior predictable and prevents the same index being created from multiple code paths.

## Startup sequence

During API startup, the `lifespan` function in `dishka_lifespan.py` initializes Beanie with the MongoDB client, then resolves the `KafkaBroker` from DI, registers FastStream subscribers, sets up Dishka integration, and starts the broker. Workers follow the same pattern — they connect to MongoDB, initialize Beanie, register their subscribers on the broker, and start consuming.

## Local development

To force a specific MongoDB migration to run again, delete its document from `schema_versions`. To start fresh, point the app at a new database. Migrations are designed to be additive; the system doesn't support automatic rollbacks. If you need to undo a migration in production, you'll have to drop indexes or modify validators manually.

## Key files

| File                                                                                                                           | Purpose                    |
|--------------------------------------------------------------------------------------------------------------------------------|----------------------------|
| [`schema_manager.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/schema/schema_manager.py)             | MongoDB migrations         |
| [`typed.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/domain/events/typed.py)                           | Domain events (Pydantic BaseModel) |
| [`mappings.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/infrastructure/kafka/mappings.py)              | Event-to-topic routing     |
| [`dishka_lifespan.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/dishka_lifespan.py)                | Startup initialization     |
