"""E2E tests conftest.

Workers run in containers via docker compose. Tests just hit the API.
"""
import logging
from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database

from tests.helpers.cleanup import cleanup_db_and_redis

_e2e_logger = logging.getLogger("test.e2e")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> Any:
    """Clean DB and Redis before each E2E test."""
    await cleanup_db_and_redis(db, redis_client)
    yield


@pytest_asyncio.fixture(scope="module")
async def execution_workers() -> AsyncGenerator[None, None]:
    """No-op fixture for backwards compatibility.

    Workers run in containers via docker compose.
    This fixture exists so tests that depend on it don't break.
    """
    _e2e_logger.info("Workers running in containers")
    yield None
