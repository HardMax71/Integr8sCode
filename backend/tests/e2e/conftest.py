"""E2E tests conftest - with infrastructure cleanup."""
from collections.abc import AsyncGenerator

import pytest_asyncio
import redis.asyncio as redis

from app.core.database_context import Database
from tests.helpers.cleanup import cleanup_db_and_redis


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> AsyncGenerator[None, None]:
    """Clean DB and Redis before each E2E test.

    Only pre-test cleanup - post-test cleanup causes event loop issues
    when SSE/streaming tests hold connections across loop boundaries.
    """
    await cleanup_db_and_redis(db, redis_client)
    yield
    # No post-test cleanup to avoid "Event loop is closed" errors
