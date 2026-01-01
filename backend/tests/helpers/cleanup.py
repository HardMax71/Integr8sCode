"""Shared cleanup utilities for integration and E2E tests."""
import redis.asyncio as redis
from beanie import init_beanie

from app.core.database_context import Database
from app.db.docs import ALL_DOCUMENTS


async def cleanup_db_and_redis(db: Database, redis_client: redis.Redis) -> None:
    """Clean DB and Redis before a test.

    NOTE: With pytest-xdist, each worker uses a separate Redis database
    (gw0→db0, gw1→db1, etc.), so flushdb() is safe and only affects
    that worker's database. See tests/conftest.py for REDIS_DB setup.
    """
    collections = await db.list_collection_names()
    for name in collections:
        if not name.startswith("system."):
            await db.drop_collection(name)

    await redis_client.flushdb()

    await init_beanie(database=db, document_models=ALL_DOCUMENTS)
