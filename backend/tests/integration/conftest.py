"""Integration tests conftest - with infrastructure cleanup."""
import uuid
from collections.abc import AsyncGenerator, Callable

import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database

from tests.helpers.cleanup import cleanup_db_and_redis


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> AsyncGenerator[None, None]:
    """Clean DB and Redis before each integration test.

    Only pre-test cleanup - post-test cleanup causes event loop issues
    when SSE/streaming tests hold connections across loop boundaries.
    """
    await cleanup_db_and_redis(db, redis_client)
    yield
    # No post-test cleanup to avoid "Event loop is closed" errors


@pytest.fixture
def unique_id(request: pytest.FixtureRequest) -> Callable[[str], str]:
    """Generate unique IDs with a prefix for test isolation.

    Usage:
        def test_something(unique_id):
            exec_id = unique_id("exec-")
            event_id = unique_id("evt-")
    """
    suffix = f"{request.node.name[:15]}-{uuid.uuid4().hex[:8]}"

    def _make(prefix: str = "") -> str:
        return f"{prefix}{suffix}"

    return _make
