# tests/conftest.py
import pathlib
from typing import AsyncGenerator, Optional

import httpx
import pytest
from app.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

ENV_FILE_PATH = pathlib.Path(__file__).parent.parent / '.env.test'

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
    print(f"DEBUG: Attempting to load settings from calculated path: {ENV_FILE_PATH}")
    if not ENV_FILE_PATH.is_file(): # Use .is_file() for Path objects
        print(f"DEBUG: File NOT found at {ENV_FILE_PATH}")
        cwd_env_path = pathlib.Path('.env.test').resolve()
        print(f"DEBUG: Also checking relative to CWD: {cwd_env_path}")
        if cwd_env_path.is_file():
             print(f"DEBUG: Found .env.test relative to CWD. Using that.")
             settings_env_file = cwd_env_path
        else:
             pytest.fail(f".env.test file not found at expected locations: {ENV_FILE_PATH} or {cwd_env_path}")
    else:
        print(f"DEBUG: File found at {ENV_FILE_PATH}")
        settings_env_file = ENV_FILE_PATH

    try:
        settings = Settings(_env_file=settings_env_file, _env_file_encoding='utf-8')
        print(f"DEBUG: Settings loaded. MONGODB_URL='{settings.MONGODB_URL}', PROJECT_NAME='{settings.PROJECT_NAME}'")
    except Exception as load_exc:
         pytest.fail(f"Failed to load settings from {settings_env_file}: {load_exc}")

    if not settings.MONGODB_URL or not settings.PROJECT_NAME or "localhost:27017" not in settings.MONGODB_URL:
        pytest.fail(f"Failed to load correct MONGODB_URL (expecting localhost) from {settings_env_file}. Loaded URL: '{settings.MONGODB_URL}'")

    db_client: Optional[AsyncIOMotorClient] = None
    try:
        db_client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            tz_aware=True,
            serverSelectionTimeoutMS=5000
        )
        test_db_name = settings.PROJECT_NAME
        database = db_client.get_database(test_db_name)

        # Verify connection
        await db_client.admin.command("ping")
        print(f"DEBUG: Successfully connected to DB '{test_db_name}' at '{settings.MONGODB_URL}'")

        yield database

        await db_client.drop_database(test_db_name)

    except Exception as e:
        pytest.fail(f"DB Fixture Error: Failed setting up/cleaning test database '{settings.PROJECT_NAME}' "
                    f"using URL '{settings.MONGODB_URL}': {e}", pytrace=True)
    finally:
        if db_client:
            db_client.close()
