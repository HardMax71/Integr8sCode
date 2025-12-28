"""Integration tests conftest - with infrastructure cleanup."""
import pytest_asyncio
import redis.asyncio as redis

from app.core.database_context import Database


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis):
    """Clean DB and Redis before each integration test.

    Only pre-test cleanup - post-test cleanup causes event loop issues
    when SSE/streaming tests hold connections across loop boundaries.
    """
    collections = await db.list_collection_names()
    for name in collections:
        if not name.startswith("system."):
            await db.drop_collection(name)
    await redis_client.flushdb()

    yield
    # No post-test cleanup to avoid "Event loop is closed" errors
