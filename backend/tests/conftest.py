import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from dishka import AsyncContainer, Provider, Scope, provide
from httpx import ASGITransport
from pydantic_settings import SettingsConfigDict

from app.core.container import create_app_container
from app.core.database_context import Database
from app.main import create_app
from app.settings import Settings
import redis.asyncio as redis


# ===== Test Settings =====
class TestSettings(Settings):
    """Test configuration - loads from .env.test instead of .env"""

    model_config = SettingsConfigDict(
        env_file=".env.test",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Allow extra env vars in test environment
    )


class TestSettingsProvider(Provider):
    """Provides TestSettings instance to the DI container."""

    scope = Scope.APP

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @provide
    def get_settings(self) -> Settings:
        return self._settings


# ===== Worker-specific isolation for pytest-xdist =====
def _compute_worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "gw0")


def _setup_worker_env() -> None:
    """Set worker-specific environment variables for pytest-xdist isolation.

    Must be called BEFORE TestSettings is instantiated so env vars are picked up.
    """
    session_id = os.environ.get("PYTEST_SESSION_ID") or uuid.uuid4().hex[:8]
    worker_id = _compute_worker_id()
    os.environ["PYTEST_SESSION_ID"] = session_id

    # Unique database name per worker
    os.environ["DATABASE_NAME"] = f"integr8scode_test_{session_id}_{worker_id}"

    # Distribute Redis DBs across workers (0-15)
    try:
        worker_num = int(worker_id[2:]) if worker_id.startswith("gw") else 0
        os.environ["REDIS_DB"] = str(worker_num % 16)
    except Exception:
        os.environ.setdefault("REDIS_DB", "0")

    # Unique Kafka consumer group per worker
    os.environ["KAFKA_GROUP_SUFFIX"] = f"{session_id}.{worker_id}"

    # Unique Schema Registry prefix per worker
    os.environ["SCHEMA_SUBJECT_PREFIX"] = f"test.{session_id}.{worker_id}."


# Set up worker env at module load time (before any Settings instantiation)
_setup_worker_env()


# ===== App fixture with DI =====
@pytest_asyncio.fixture(scope="session")
async def app():
    """Create FastAPI app with test DI container.

    Session-scoped to avoid Pydantic schema validator memory issues when
    FastAPI recreates OpenAPI schemas hundreds of times with pytest-xdist.
    See: https://github.com/pydantic/pydantic/issues/1864
    """
    # Create test settings and container
    test_settings = TestSettings()
    container = create_app_container(settings_provider=TestSettingsProvider(test_settings))

    # Create app with test container
    application = create_app(container=container)

    yield application

    # Cleanup
    if hasattr(application.state, "dishka_container"):
        await application.state.dishka_container.close()


@pytest_asyncio.fixture(scope="session")
async def app_container(app):  # type: ignore[valid-type]
    """Expose the Dishka container attached to the app."""
    container: AsyncContainer = app.state.dishka_container  # type: ignore[attr-defined]
    return container


# ===== Client (function-scoped for clean cookies per test) =====
@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:  # type: ignore[valid-type]
    """HTTP client for testing API endpoints."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        timeout=30.0,
        follow_redirects=True,
    ) as c:
        yield c


# ===== Request-scope accessor =====
@asynccontextmanager
async def _container_scope(container: AsyncContainer):
    async with container() as scope:  # type: ignore[misc]
        yield scope


@pytest_asyncio.fixture
async def scope(app_container: AsyncContainer):  # type: ignore[valid-type]
    async with _container_scope(app_container) as s:
        yield s


@pytest_asyncio.fixture
async def db(scope) -> AsyncGenerator[Database, None]:  # type: ignore[valid-type]
    database: Database = await scope.get(Database)
    yield database


@pytest_asyncio.fixture
async def redis_client(scope) -> AsyncGenerator[redis.Redis, None]:  # type: ignore[valid-type]
    client: redis.Redis = await scope.get(redis.Redis)
    yield client


# ===== HTTP helpers (auth) =====
async def _http_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    data = {"username": username, "password": password}
    resp = await client.post("/api/v1/auth/login", data=data)
    resp.raise_for_status()
    return resp.json().get("csrf_token", "")


@pytest.fixture
def test_user_credentials():
    uid = uuid.uuid4().hex[:8]
    return {
        "username": f"test_user_{uid}",
        "email": f"test_user_{uid}@example.com",
        "password": "TestPass123!",
        "role": "user",
    }


@pytest.fixture
def test_admin_credentials():
    uid = uuid.uuid4().hex[:8]
    return {
        "username": f"admin_user_{uid}",
        "email": f"admin_user_{uid}@example.com",
        "password": "AdminPass123!",
        "role": "admin",
    }


@pytest_asyncio.fixture
async def test_user(client: httpx.AsyncClient, test_user_credentials):
    """Function-scoped authenticated user."""
    creds = test_user_credentials
    r = await client.post("/api/v1/auth/register", json=creds)
    if r.status_code not in (200, 201, 400):
        pytest.fail(f"Cannot create test user (status {r.status_code}): {r.text}")
    csrf = await _http_login(client, creds["username"], creds["password"])
    return {**creds, "csrf_token": csrf, "headers": {"X-CSRF-Token": csrf}}


@pytest_asyncio.fixture
async def test_admin(client: httpx.AsyncClient, test_admin_credentials):
    """Function-scoped authenticated admin."""
    creds = test_admin_credentials
    r = await client.post("/api/v1/auth/register", json=creds)
    if r.status_code not in (200, 201, 400):
        pytest.fail(f"Cannot create test admin (status {r.status_code}): {r.text}")
    csrf = await _http_login(client, creds["username"], creds["password"])
    return {**creds, "csrf_token": csrf, "headers": {"X-CSRF-Token": csrf}}


@pytest_asyncio.fixture
async def another_user(client: httpx.AsyncClient):
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "TestPass123!"
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "role": "user",
        },
    )
    csrf = await _http_login(client, username, password)
    return {
        "username": username,
        "email": email,
        "password": password,
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf},
    }
