import redis.asyncio as redis
from app.core.database_context import Database


async def cleanup_db_and_redis(db: Database, redis_client: redis.Redis) -> None:
    """Clean DB and Redis before a test.

    Beanie is already initialized once during app lifespan (dishka_lifespan.py).
    We just delete documents to preserve indexes and avoid file descriptor exhaustion.

    NOTE: With pytest-xdist, each worker is assigned a dedicated Redis DB
    derived from the worker id (sum(_WORKER_ID.encode()) % 16), so flushdb()
    is safe and only affects that worker's database. See tests/conftest.py
    for REDIS_DB setup.
    """
    collections = await db.list_collection_names(filter={"type": "collection"})
    for name in collections:
        if not name.startswith("system."):
            await db[name].delete_many({})

    await redis_client.flushdb()
