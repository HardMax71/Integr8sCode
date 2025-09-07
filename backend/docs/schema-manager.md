Schema management in this codebase

The backend initializes MongoDB schema at process start using a small SchemaManager. It applies a list of ordered, idempotent migrations that create named indexes and set collection validators. Results are recorded in `schema_versions`, so each migration runs once per database.

When the API boots, the lifespan hook gets the database from DI and runs `apply_all()`. The same call exists in long‑running workers after they connect to Mongo. Repositories don’t create indexes or validators; they read and write only. That separation prevents duplicate work and makes startup behavior clear.

Each migration is a short function. If you need to evolve the schema, add a new function and append it to the list in `apply_all()` with a unique id and a short description. Use meaningful index names so re‑runs are safe; Mongo will no‑op on matching names/specs. Validators are applied with non‑blocking settings and log warnings if they can’t be updated.

To keep startup fast, `apply_all()` first checks whether both the first and the last migration ids are present in `schema_versions`. If they are, it assumes everything in between has been applied and returns early. If not, it walks the list and applies only what’s missing.

For local testing, you can drop a document from `schema_versions` to force a specific migration to run again, or point the app to a fresh database. In production, migrations should be additive; rollbacks aren’t supported by this simple mechanism and should be handled manually if ever needed.

