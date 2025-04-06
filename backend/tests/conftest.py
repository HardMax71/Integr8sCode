# tests/conftest.py
import asyncio
from asyncio import AbstractEventLoop
from typing import AsyncGenerator, Generator

import pytest
from app.config import Settings
from app.main import create_app
from fastapi import FastAPI
from httpx import AsyncClient
import httpx
from motor.motor_asyncio import AsyncIOMotorClient


def get_test_settings() -> Settings:
    return Settings(
        PROJECT_NAME="Integr8sCode_test",
        MONGODB_URL="mongodb://localhost:27017",
        SECRET_KEY="test_secret_key",
        TESTING=True,
    )


@pytest.fixture(scope="session")
def event_loop() -> Generator[AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    backend_service_url = "https://localhost:443"

    async with AsyncClient(
        base_url=backend_service_url,
        verify=False
    ) as async_client:
        try:
             response = await async_client.get("/api/v1/health", timeout=15)
             response.raise_for_status() # Raise exception for non-2xx status
             print(f"Initial health check to {backend_service_url} successful.")
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
             pytest.fail(f"Failed initial connection to backend service at {backend_service_url}: {e}", pytrace=False)

        yield async_client


@pytest.fixture(scope="function")
async def db() -> AsyncGenerator:
    settings = get_test_settings()
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.MONGODB_URL, tz_aware=True)
    db = client[settings.PROJECT_NAME]
    yield db
    await client.drop_database(settings.PROJECT_NAME)
    client.close()
