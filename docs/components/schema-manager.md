# Schema management

The backend manages MongoDB collection schemas — indexes, validators, and TTL policies. These are initialized at process start, whether the process is the main API or a standalone worker.

Kafka event serialization is handled entirely by FastStream with Pydantic JSON; there is no schema registry involved. See [Event System Design](../architecture/event-system-design.md) for details on event serialization.

## MongoDB schema

MongoDB indexes and validators are defined declaratively on each Beanie `Document` subclass via an inner `Settings` class. When `init_beanie()` runs at startup, Beanie reads the `indexes` list from every registered document model and calls `create_indexes` on the collection. Because `create_indexes` is idempotent (a no-op when an index with the same name and spec already exists), every process can safely call `init_beanie()` on boot without worrying about duplicate work.

Each document class owns its own index definitions. For example, the events collection declares a unique index on `event_id`, compound indexes for queries by event type, aggregate, user, service, and status, a TTL index for automatic expiration, and a text search index across several fields. Other documents define TTL indexes for idempotency keys (one-hour TTL) and DLQ messages (seven-day TTL) so old documents are cleaned up automatically.

Repositories don't create their own indexes — they only read and write. This separation keeps startup behavior predictable and prevents the same index being created from multiple code paths.

## Startup sequence

During API startup, the `lifespan` function in `dishka_lifespan.py` initializes Beanie with the MongoDB client, then resolves the `KafkaBroker` from DI, registers FastStream subscribers, sets up Dishka integration, and starts the broker. Workers follow the same pattern — they connect to MongoDB, initialize Beanie, register their subscribers on the broker, and start consuming.

## Local development

Indexes are additive and idempotent. To rebuild an index with different options, drop it manually in `mongosh` and restart the process — `init_beanie()` will recreate it from the document class definition. To start fresh, point the app at a new database.

## Key files

| File                                                                                                                           | Purpose                    |
|--------------------------------------------------------------------------------------------------------------------------------|----------------------------|
| [`typed.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/domain/events/typed.py)                           | Domain events (Pydantic BaseModel) |
| [`dishka_lifespan.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/dishka_lifespan.py)                | Startup initialization     |
