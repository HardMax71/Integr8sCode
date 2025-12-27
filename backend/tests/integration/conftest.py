"""Integration tests conftest - with infrastructure cleanup."""
import pytest_asyncio
import redis.asyncio as redis

from app.core.database_context import Database


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis):
    """Clean DB and Redis before/after each integration test."""
    # Pre-test cleanup
    collections = await db.list_collection_names()
    for name in collections:
        if not name.startswith("system."):
            await db.drop_collection(name)
    await redis_client.flushdb()

    yield

    # Post-test cleanup
    collections = await db.list_collection_names()
    for name in collections:
        if not name.startswith("system."):
            await db.drop_collection(name)
    await redis_client.flushdb()
