import asyncio
import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from app.main import create_app
from app.config import get_settings, Settings

@pytest.fixture(scope="session")
def test_settings():
    return Settings(
        TESTING=True,
        MONGODB_URL="mongodb://localhost:27018/test_db",
        PROJECT_NAME="integr8scode"
    )


@pytest.fixture(scope="session")
def test_app(test_settings):
    app = create_app()
    # Override the get_settings dependency
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app) as client:
        yield client

@pytest.fixture(scope="session")
async def test_db(test_settings):
    client = AsyncIOMotorClient(test_settings.MONGODB_URL)
    db = client[test_settings.PROJECT_NAME]
    yield db
    await client.drop_database(test_settings.PROJECT_NAME)
    client.close()
