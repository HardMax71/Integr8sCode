"""E2E tests - hit real containers via HTTP."""
import ssl
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from app.main import create_app
from app.settings import Settings
from fastapi import FastAPI


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """E2E tests use Settings matching containers (no worker isolation)."""
    return Settings()


@pytest_asyncio.fixture(scope="session")
async def app(test_settings: Settings) -> AsyncGenerator[FastAPI, None]:
    """App using container-matching settings."""
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
        base_url=f"https://localhost:{test_settings.SERVER_PORT}",
        timeout=60.0,
        follow_redirects=True,
        verify=ssl_context,
    ) as c:
        yield c
