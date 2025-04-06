# tests/conftest.py
from typing import AsyncGenerator, Optional

import httpx
import pytest
from app.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    backend_service_url = "https://localhost:443"
    async with httpx.AsyncClient(
            base_url=backend_service_url,
            verify=False,
            timeout=30.0
    ) as async_client:
        try:
            response = await async_client.get("/api/v1/health", timeout=15)
            response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            pytest.fail(f"Failed initial connection/health check to backend service at {backend_service_url}: {e}",
                        pytrace=False)

        yield async_client
    # Client is automatically closed here by async context manager


@pytest.fixture(scope="function")
async def db() -> AsyncGenerator[AsyncIOMotorDatabase, None]:
    settings = Settings(_env_file='/tests/.env.test', _env_file_encoding='utf-8')
    if not settings.MONGODB_URL or not settings.PROJECT_NAME:
        pytest.fail("MONGODB_URL or PROJECT_NAME not configured for testing")

    db_client: Optional[AsyncIOMotorClient] = None
    try:
        db_client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            tz_aware=True,
            serverSelectionTimeoutMS=5000
        )
        test_db_name = settings.PROJECT_NAME
        database = db_client.get_database(test_db_name)

        await db_client.admin.command("ping")

        yield database

        await db_client.drop_database(test_db_name)

    except Exception as e:
        pytest.fail(f"DB Fixture Error: Failed setting up/cleaning test database '{settings.PROJECT_NAME}' "
                    f"at {settings.MONGODB_URL}: {e}", pytrace=True)
    finally:
        if db_client:
            db_client.close()
