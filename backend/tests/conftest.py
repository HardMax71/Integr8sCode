import os
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database
from app.domain.enums.user import UserRole
from app.main import create_app
from app.settings import Settings
from dishka import AsyncContainer
from fastapi import FastAPI
from httpx import ASGITransport
from pydantic_settings import SettingsConfigDict


class TestSettings(Settings):
    """Test configuration - loads from .env.test instead of .env"""

    model_config = SettingsConfigDict(
        env_file=".env.test",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


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

    # Disable OpenTelemetry exporters to prevent "otel-collector:4317" retry noise
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
    os.environ["OTEL_METRICS_EXPORTER"] = "none"
    os.environ["OTEL_TRACES_EXPORTER"] = "none"
    os.environ["OTEL_LOGS_EXPORTER"] = "none"


# Set up worker env at module load time (before any Settings instantiation)
_setup_worker_env()


# ===== Settings fixture =====
@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Provide TestSettings for tests that need to create their own components."""
    return TestSettings()


# ===== App fixture =====
@pytest_asyncio.fixture(scope="session")
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with TestSettings.

    Session-scoped to avoid Pydantic schema validator memory issues when
    FastAPI recreates OpenAPI schemas hundreds of times with pytest-xdist.
    """
    application = create_app(settings=TestSettings())

    yield application

    await application.state.dishka_container.close()


@pytest_asyncio.fixture(scope="session")
async def app_container(app: FastAPI) -> AsyncContainer:
    """Expose the Dishka container attached to the app."""
    container: AsyncContainer = app.state.dishka_container
    return container


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client for testing API endpoints."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        timeout=30.0,
        follow_redirects=True,
    ) as c:
        yield c


@asynccontextmanager
async def _container_scope(container: AsyncContainer) -> AsyncGenerator[AsyncContainer, None]:
    async with container() as scope:
        yield scope


@pytest_asyncio.fixture
async def scope(app_container: AsyncContainer) -> AsyncGenerator[AsyncContainer, None]:
    async with _container_scope(app_container) as s:
        yield s


@pytest_asyncio.fixture
async def db(scope: AsyncContainer) -> AsyncGenerator[Database, None]:
    database = await scope.get(Database)
    yield database


@pytest_asyncio.fixture
async def redis_client(scope: AsyncContainer) -> AsyncGenerator[redis.Redis, None]:
    client = await scope.get(redis.Redis)
    yield client


# ===== User creation & authentication =====
async def _register_and_login(
    client: httpx.AsyncClient, role: UserRole = UserRole.USER
) -> dict[str, Any]:
    """Create user with role, register, login, return user info with CSRF headers."""
    uid = uuid.uuid4().hex[:8]
    creds = {
        "username": f"{role.value}_{uid}",
        "email": f"{role.value}_{uid}@example.com",
        "password": "TestPass123!",
        "role": role.value,
    }
    r = await client.post("/api/v1/auth/register", json=creds)
    if r.status_code not in (200, 201, 400):
        pytest.fail(f"Cannot create {role.value}: {r.status_code} - {r.text}")

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": creds["username"], "password": creds["password"]},
    )
    resp.raise_for_status()
    csrf: str = resp.json().get("csrf_token", "")
    return {**creds, "csrf_token": csrf, "headers": {"X-CSRF-Token": csrf}}


# Type alias for the make_user factory
MakeUser = Callable[[UserRole], Coroutine[Any, Any, dict[str, Any]]]


@pytest_asyncio.fixture
async def make_user(client: httpx.AsyncClient) -> MakeUser:
    """Factory to create users with any role. Use for isolation tests.

    Example:
        user1 = await make_user(UserRole.USER)
        user2 = await make_user(UserRole.USER)  # another user
        admin = await make_user(UserRole.ADMIN)
    """

    async def _make(role: UserRole = UserRole.USER) -> dict[str, Any]:
        return await _register_and_login(client, role)

    return _make


@pytest_asyncio.fixture
async def authenticated_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """HTTP client logged in as regular user.

    Note: This fixture mutates and returns the same `client` instance with
    auth headers applied. Do NOT use both `client` and `authenticated_client`
    in the same test. For multi-user tests, use `client` + `make_user` fixture.
    """
    user = await _register_and_login(client, UserRole.USER)
    client.headers.update(user["headers"])
    return client


@pytest_asyncio.fixture
async def authenticated_admin_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """HTTP client logged in as admin.

    Note: This fixture mutates and returns the same `client` instance with
    admin auth headers applied. For multi-user tests, use `make_user` fixture.
    """
    admin = await _register_and_login(client, UserRole.ADMIN)
    client.headers.update(admin["headers"])
    return client
