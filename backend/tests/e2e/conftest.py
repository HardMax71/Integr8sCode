"""E2E tests conftest.

Workers run in containers via docker compose. Tests hit the real API.
"""
import logging
import os
import ssl
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database

from tests.helpers.cleanup import cleanup_db_and_redis

_e2e_logger = logging.getLogger("test.e2e")

# Backend URL for E2E tests (set in CI, defaults to local HTTPS)
BACKEND_URL = os.environ.get("BACKEND_URL", "https://localhost:443")


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client for E2E tests - hits real backend, not ASGI transport.

    Uses BACKEND_URL env var (defaults to https://localhost:443).
    Trusts self-signed certs for local/CI testing.
    """
    _e2e_logger.info(f"E2E client connecting to {BACKEND_URL}")

    # Create SSL context that doesn't verify certs (self-signed in dev/CI)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(
        base_url=BACKEND_URL,
        timeout=60.0,
        follow_redirects=True,
        verify=ssl_context,
    ) as c:
        yield c


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
