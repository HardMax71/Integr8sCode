"""E2E tests - hit real containers via HTTP."""
import ssl
from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database
from app.main import create_app
from app.settings import Settings
from fastapi import FastAPI

from tests.helpers.cleanup import cleanup_db_and_redis


@pytest_asyncio.fixture(scope="session")
async def app(test_settings: Settings) -> AsyncGenerator[FastAPI, None]:
    """App using test_settings from .env.test."""
    application = create_app(settings=test_settings)
    yield application
    await application.state.dishka_container.close()


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client hitting real backend containers."""
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(
        base_url=f"https://localhost:{test_settings.HTTPS_PORT}",
        timeout=60.0,
        follow_redirects=True,
        verify=ssl_context,
    ) as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> AsyncGenerator[None, None]:
    """Clean DB and Redis before each E2E test."""
    await cleanup_db_and_redis(db, redis_client)
    yield
