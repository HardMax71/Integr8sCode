import os
import pathlib
import ssl
from typing import AsyncGenerator, Optional

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings
from app.schemas_pydantic.user import UserInDB, UserRole


def create_test_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


ENV_FILE_PATH = pathlib.Path(__file__).parent / '.env.test'


@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    backend_service_url = "https://localhost:443"
    async with httpx.AsyncClient(
            base_url=backend_service_url,
            verify=create_test_ssl_context(),
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
    if not ENV_FILE_PATH.is_file():  # Use .is_file() for Path objects
        print(f"DEBUG: File NOT found at {ENV_FILE_PATH}")
        cwd_env_path = pathlib.Path('.env.test').resolve()
        print(f"DEBUG: Also checking relative to CWD: {cwd_env_path}")
        if cwd_env_path.is_file():
            print("DEBUG: Found .env.test relative to CWD. Using that.")
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
        pytest.fail(
            f"Failed to load correct MONGODB_URL (expecting localhost) from {settings_env_file}. Loaded URL: '{settings.MONGODB_URL}'")

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


# Additional fixtures for event-driven testing

@pytest.fixture(scope="function")
async def kafka_admin():
    """Provide Kafka admin client for test setup"""
    from aiokafka.admin import AIOKafkaAdminClient

    admin = AIOKafkaAdminClient(
        bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
    )

    await admin.start()
    yield admin
    await admin.close()


@pytest.fixture(scope="function")
def mock_settings(monkeypatch):
    """Mock settings for tests"""
    test_settings = Settings(
        TESTING=True,
        SECRET_KEY="test-secret-key-for-testing-only-32chars",
        MONGODB_URL=os.environ.get("MONGODB_URL", "mongodb://mongo:27017/integr8scode_test"),
        KAFKA_BOOTSTRAP_SERVERS=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092"),
        KAFKA_DLQ_TOPIC="test-dead-letter-queue",
        ENABLE_EVENT_STREAMING=True,
        ENABLE_TRACING=False,  # Disable tracing in tests
    )

    monkeypatch.setattr("app.config.get_settings", lambda: test_settings)

    return test_settings


@pytest.fixture(scope="function")
async def test_user(db: AsyncIOMotorDatabase):
    """Create test user for authenticated endpoints"""
    from app.schemas_pydantic.user import UserCreate
    from app.db.repositories.user_repository import UserRepository
    from passlib.context import CryptContext

    user_repo = UserRepository(db)
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    test_user_data = UserCreate(
        username="testuser",
        email="test@example.com",
        password="testpassword123"
    )

    # Hash the password before creating the user
    hashed_password = pwd_context.hash(test_user_data.password)

    user = await user_repo.create_user(UserInDB(
        username=test_user_data.username,
        email=test_user_data.email,
        role=UserRole.USER,
        is_active=True,
        hashed_password=hashed_password
    ))

    yield user

    # Cleanup
    await db.users.delete_one({"user_id": user.user_id})


@pytest.fixture(scope="function")
async def auth_headers(test_user):
    """Generate auth headers for test requests"""
    from app.core.security import SecurityService
    from app.config import get_settings

    settings = get_settings()
    security_service = SecurityService()

    token = security_service.create_access_token(data={"sub": test_user.username})

    return {"Authorization": f"Bearer {token}"}


# Markers for different test types
def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "kafka: mark test as requiring Kafka"
    )
    config.addinivalue_line(
        "markers", "mongodb: mark test as requiring MongoDB"
    )
