import asyncio
import os
import logging
import pathlib
import ssl
from typing import AsyncGenerator, Optional, Dict, Callable, Awaitable
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from passlib.context import CryptContext

from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import UserInDB
from app.settings import Settings


# ===== Environment Setup (from unit/conftest.py) =====
# Disable OpenTelemetry completely for tests via environment and app settings
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")
os.environ.setdefault("OTEL_LOGS_EXPORTER", "none")
# Ensure application Settings sees tracing disabled
os.environ.setdefault("ENABLE_TRACING", "false")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")


# ===== Mock Database for Unit Tests (from unit/db/repositories/conftest.py) =====
class MockMotorDatabase:
    """Lightweight async Motor-like database mock.

    - Attribute access returns/stores an AsyncMock collection
    - get_collection(name) returns the same collection
    - __getitem__(name) supports bracket access used in some repos
    """

    def __init__(self) -> None:
        self._collections: Dict[str, AsyncIOMotorCollection] = {}

    def _get_or_create(self, name: str) -> AsyncIOMotorCollection:
        if name not in self._collections:
            mock = AsyncMock(spec=AsyncIOMotorCollection)
            # Set common methods as AsyncMock with default return values
            mock.insert_one = AsyncMock()
            mock.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
            mock.find_one = AsyncMock()
            mock.delete_one = AsyncMock()
            mock.count_documents = AsyncMock()
            self._collections[name] = mock
        return self._collections[name]

    def __getattr__(self, name: str) -> AsyncIOMotorCollection:
        return self._get_or_create(name)

    def __getitem__(self, name: str) -> AsyncIOMotorCollection:
        return self._get_or_create(name)

    def get_collection(self, name: str) -> AsyncIOMotorCollection:  # sync method as in Motor
        return self._get_or_create(name)


@pytest.fixture()
def mock_db() -> MockMotorDatabase:
    """Shared mock database for repository unit tests."""
    return MockMotorDatabase()


# ===== SSL and HTTP Helpers =====
def create_test_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


ENV_FILE_PATH = pathlib.Path(__file__).parent / '.env.test'


# ===== Base URL and Client Fixtures =====
@pytest.fixture(scope="session")
def selected_base_url() -> str:
    # Determine once per session the working base URL
    candidates = [
        os.environ.get("BACKEND_BASE_URL"),
        # Prefer explicit IPv4/IPv6 loopbacks to avoid resolver ambiguity
        "https://127.0.0.1:443",
        "https://[::1]:443",
        "https://localhost:443",
    ]
    candidates = [c for c in candidates if c]
    # Probe backend health endpoints first; fall back to OpenAPI if enabled
    health_paths = [
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/openapi.json",
    ]

    ctx = create_test_ssl_context()
    for base in candidates:
        try:
            with httpx.Client(base_url=base, verify=ctx, timeout=5.0) as c:
                for hp in health_paths:
                    try:
                        r = c.get(hp)
                        if r.status_code == 200:
                            os.environ["BACKEND_BASE_URL"] = base
                            return base
                    except Exception:
                        continue
        except Exception:
            continue
    pytest.fail(f"No healthy backend base URL found among: {candidates}")


@pytest.fixture(scope="function")
async def client(selected_base_url: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        base_url=selected_base_url,
        verify=create_test_ssl_context(),
        timeout=30.0,
    ) as async_client:
        yield async_client


# Note: in-process API client moved to tests/api/conftest.py to keep integration tests
# strictly targeting the deployed backend.


# ===== Database Fixture =====
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


# ===== Integration Test Helpers (from integration/conftest.py) =====
async def _http_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    data = {"username": username, "password": password}
    resp = await client.post("/api/v1/auth/login", data=data)
    resp.raise_for_status()
    csrf_token = resp.json().get("csrf_token", "")
    return csrf_token


# Session-scoped shared user credentials (created once per test session)
@pytest.fixture(scope="session")
def shared_user_credentials():
    """Shared user credentials that can be reused across all tests."""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    return {
        "username": f"test_user_{unique_id}",
        "email": f"test_user_{unique_id}@example.com",
        "password": "TestPass123!",
        "role": "user"
    }


@pytest.fixture(scope="session")
def shared_admin_credentials():
    """Shared admin credentials that can be reused across all tests."""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    return {
        "username": f"admin_user_{unique_id}",
        "email": f"admin_user_{unique_id}@example.com",
        "password": "AdminPass123!",
        "role": "admin"
    }


# Session-scoped tracking of created users
_created_users = set()

# Function-scoped fixture that ensures user exists and returns auth headers
@pytest.fixture(scope="function")
async def shared_user(client: httpx.AsyncClient, shared_user_credentials) -> dict[str, str]:
    """Ensure shared user exists and return auth headers for current test."""
    creds = shared_user_credentials
    
    # Only try to create the user once per session
    if creds["username"] not in _created_users:
        payload = {
            "username": creds["username"],
            "email": creds["email"],
            "password": creds["password"],
            "role": creds["role"]
        }
        r = await client.post("/api/v1/auth/register", json=payload)
        
        if r.status_code in (200, 201):
            _created_users.add(creds["username"])
        elif r.status_code == 400:
            # User already exists from a previous test run
            _created_users.add(creds["username"])
        else:
            pytest.skip(f"Cannot create shared user (status {r.status_code}). Rate limit may be active.")
    
    # Always login to get fresh CSRF token for this test
    csrf = await _http_login(client, creds["username"], creds["password"])
    
    return {
        "username": creds["username"],
        "email": creds["email"],
        "password": creds["password"],
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf}
    }


# Function-scoped fixture that ensures admin exists and returns auth headers
@pytest.fixture(scope="function")
async def shared_admin(client: httpx.AsyncClient, shared_admin_credentials) -> dict[str, str]:
    """Ensure shared admin exists and return auth headers for current test."""
    creds = shared_admin_credentials
    
    # Only try to create the admin once per session
    if creds["username"] not in _created_users:
        payload = {
            "username": creds["username"],
            "email": creds["email"],
            "password": creds["password"],
            "role": creds["role"]
        }
        r = await client.post("/api/v1/auth/register", json=payload)
        
        if r.status_code in (200, 201):
            _created_users.add(creds["username"])
        elif r.status_code == 400:
            # User already exists from a previous test run
            _created_users.add(creds["username"])
        else:
            pytest.skip(f"Cannot create shared admin (status {r.status_code}). Rate limit may be active.")
    
    # Always login to get fresh CSRF token for this test
    csrf = await _http_login(client, creds["username"], creds["password"])
    
    return {
        "username": creds["username"],
        "email": creds["email"],
        "password": creds["password"],
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf}
    }

@pytest.fixture(scope="function")
async def another_user(client: httpx.AsyncClient) -> dict[str, str]:
    """Create and return a second regular user for access control tests."""
    import uuid
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "TestPass123!"

    # Attempt to register; ignore if exists
    await client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
        "role": "user",
    })
    csrf = await _http_login(client, username, password)
    return {
        "username": username,
        "email": email,
        "password": password,
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf},
    }


# Keep the make_user fixture for tests that truly need unique users
@pytest.fixture(scope="function")
async def make_user(client: httpx.AsyncClient) -> Callable[[str, str, str], Awaitable[dict[str, str]]]:
    """Create a unique user. Use sparingly - prefer shared_user/shared_admin fixtures."""
    async def _create(username: str, email: str, password: str, *, admin: bool = False) -> dict[str, str]:
        payload = {"username": username, "email": email, "password": password}
        # Include role to create admin when requested (UserCreate allows role)
        payload["role"] = "admin" if admin else "user"
        r = await client.post("/api/v1/auth/register", json=payload)
        # 200/201 expected; if user exists, 400
        if r.status_code not in (200, 201) and r.status_code != 400:
            pytest.skip(f"Cannot create user via API (status {r.status_code}). Skipping test that depends on it.")
        return {"username": username, "email": email, "password": password, "role": payload["role"]}

    return _create


@pytest.fixture(scope="function")
async def login_user(client: httpx.AsyncClient) -> Callable[[str, str], Awaitable[str]]:  # type: ignore[name-defined]
    async def _login(username: str, password: str) -> str:
        return await _http_login(client, username, password)

    return _login


# Keep admin_session for backwards compatibility but use shared_admin internally
@pytest.fixture(scope="function")
async def admin_session(shared_admin) -> object:  # type: ignore[name-defined]
    """Admin session using the shared admin user. Returns Session object for compatibility."""
    class Session:
        def __init__(self, csrf_token: str):
            self.csrf_token = csrf_token

        def headers(self) -> dict[str, str]:
            return {"X-CSRF-Token": self.csrf_token}

    return Session(shared_admin["csrf_token"])


@pytest.fixture(scope="function")
def mock_settings(monkeypatch):
    """Mock settings for tests"""
    test_settings = Settings(
        TESTING=True,
        SECRET_KEY="test-secret-key-for-testing-only-32chars",
        MONGODB_URL=os.environ.get("MONGODB_URL", "mongodb://mongo:27017/integr8scode_test"),
        KAFKA_BOOTSTRAP_SERVERS=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092"),
        ENABLE_EVENT_STREAMING=True,
        ENABLE_TRACING=False,  # Disable tracing in tests
    )

    monkeypatch.setattr("app.config.get_settings", lambda: test_settings)

    return test_settings


# Removed unused fixtures that added overhead or external dependencies:
# - kafka_admin: not used by tests
# - DB-backed test_user/auth_headers: integration tests log in via HTTP; unit tests mock DB
# - server_coverage: disabled to avoid posting to non-existent endpoints


# ===== Markers for different test types =====
def pytest_configure(config):
    """Register custom markers"""
    # Ensure OpenTelemetry is fully disabled in the test runner process
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")
    os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
    # Silence any OTel exporter warnings that might still bubble up
    logging.getLogger("opentelemetry.exporter.otlp.proto.grpc.exporter").setLevel(logging.ERROR)
    # Disable OpenTelemetry SDK during local pytest to avoid exporter retries
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
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
