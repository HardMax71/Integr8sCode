# Schema management

The backend manages two kinds of schemas: MongoDB collections with indexes and validators, and Kafka event schemas in Avro format with a Confluent Schema Registry. Both are initialized at process start, whether the process is the main API or a standalone worker.

## MongoDB schema

The `SchemaManager` class in `app/db/schema/schema_manager.py` applies idempotent, versioned migrations to MongoDB. Each migration is a short async function that creates indexes or sets collection validators. The class tracks which migrations have run in a `schema_versions` collection, storing the migration id, description, and timestamp.

When `apply_all()` is called, it walks through an ordered list of migrations and skips any that already have a record in `schema_versions`. If the migration hasn't been applied, it runs the function and then marks it done. This design means you can safely call `apply_all()` on every startup without worrying about duplicate work — MongoDB's `create_indexes` is a no-op when indexes with matching names and specs already exist.

The system currently has nine migrations covering the main collections. The events collection gets the most attention: a unique index on `event_id`, compound indexes for queries by event type, aggregate, user, service, and status, a TTL index for automatic expiration, and a text search index across several fields. It also has a JSON schema validator set to moderate/warn mode, meaning MongoDB logs validation failures but doesn't reject writes.

Other migrations create indexes for user settings snapshots, replay sessions, notifications and notification rules, idempotency keys (with a one-hour TTL), sagas, execution results, and DLQ messages (with a seven-day TTL). The idempotency and DLQ TTL indexes automatically clean up old documents without manual intervention.

Repositories don't create their own indexes — they only read and write. This separation keeps startup behavior predictable and prevents the same index being created from multiple code paths.

## Kafka schema registry

The `SchemaRegistryManager` class in `app/events/schema/schema_registry.py` handles Avro serialization for Kafka events. It connects to a Confluent Schema Registry and registers schemas for all event types at startup.

Each event class (subclass of `BaseEvent`) generates its own Avro schema from Pydantic model definitions. The manager registers these schemas with subjects named after the class (like `ExecutionRequestedEvent-value`) and sets FORWARD compatibility, meaning new schemas can add fields but not remove required ones. This allows producers to be upgraded before consumers without breaking deserialization.

Serialization uses the Confluent wire format: a magic byte, four-byte schema id, then the Avro binary payload. The manager caches serializers per subject and maintains a bidirectional cache between schema ids and Python classes. When deserializing, it reads the schema id from the message header, looks up the corresponding event class, deserializes the Avro payload to a dict, and hydrates the Pydantic model.

For test isolation, the manager supports an optional `SCHEMA_SUBJECT_PREFIX` environment variable. Setting this to something like `test.session123.` prefixes all subject names, preventing test runs from polluting production schemas or interfering with each other.

## Startup sequence

During API startup, the `lifespan` function in `dishka_lifespan.py` gets the database from the DI container, creates a `SchemaManager`, and calls `apply_all()`. It does the same for `SchemaRegistryManager`, calling `initialize_schemas()` to register all event types. Workers like the saga orchestrator and event replay service follow the same pattern — they connect to MongoDB, run schema migrations, and initialize the schema registry before starting their main loops.

## Local development

To force a specific MongoDB migration to run again, delete its document from `schema_versions`. To start fresh, point the app at a new database. Migrations are designed to be additive; the system doesn't support automatic rollbacks. If you need to undo a migration in production, you'll have to drop indexes or modify validators manually.

For Kafka schemas, the registry keeps all versions. If you break compatibility and need to start over, delete the subject from the registry (either via REST API or the registry's UI if available) and let the app re-register on next startup.

## Key files

| File                                                                                                                           | Purpose                    |
|--------------------------------------------------------------------------------------------------------------------------------|----------------------------|
| [`schema_manager.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/schema/schema_manager.py)             | MongoDB migrations         |
| [`schema_registry.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/events/schema/schema_registry.py)       | Kafka Avro serialization   |
| [`dishka_lifespan.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/dishka_lifespan.py)                     | Startup initialization     |
