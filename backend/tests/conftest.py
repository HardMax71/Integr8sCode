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

# Disable OpenTelemetry/tracing exporters to prevent stalls from reconnection attempts
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")
os.environ.setdefault("OTEL_LOGS_EXPORTER", "none")
# Disable Jaeger tracing (custom code uses JAEGER_AGENT_HOST to build endpoint)
os.environ.setdefault("JAEGER_AGENT_HOST", "")
os.environ.setdefault("ENABLE_TRACING", "false")
# Disable rate limiting in tests (parallel workers share Redis, would hit 429s)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


class TestSettings(Settings):
    """Test configuration - loads from .env.test instead of .env."""

    model_config = SettingsConfigDict(
        env_file=".env.test",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# ===== Settings fixture with pytest-xdist worker isolation =====
@pytest.fixture(scope="session")
def test_settings(worker_id: str) -> Settings:
    """Test settings with worker-specific isolation for pytest-xdist.

    Uses the built-in worker_id fixture from pytest-xdist.
    - "master": non-xdist run, uses defaults from .env.test
    - "gw0", "gw1", etc.: xdist workers get unique DB/Redis/Kafka config
    """
    if worker_id == "master":
        return TestSettings()

    # xdist worker: create isolated settings
    worker_num = int(worker_id[2:]) if worker_id.startswith("gw") else 0

    # Set env var for schema registry (read directly from env, not Settings)
    os.environ["SCHEMA_SUBJECT_PREFIX"] = f"test.{worker_id}."

    return TestSettings(
        DATABASE_NAME=f"integr8scode_test_{worker_id}",
        REDIS_DB=worker_num % 16,
        KAFKA_GROUP_SUFFIX=worker_id,
    )


# ===== App fixture =====
@pytest_asyncio.fixture(scope="session")
async def app(test_settings: Settings) -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with worker-isolated settings.

    Session-scoped to avoid Pydantic schema validator memory issues when
    FastAPI recreates OpenAPI schemas hundreds of times with pytest-xdist.

    Runs the app lifespan to initialize Beanie ODM, schema registry, etc.
    """
    application = create_app(settings=test_settings)

    # Run lifespan to trigger init_beanie() and other startup tasks
    async with application.router.lifespan_context(application):
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
    """Create user with role, register, login, return user info with CSRF headers.

    Registration may fail with 400 if user already exists (no per-test cleanup).
    This is fine - we just proceed to login with the same credentials.
    """
    uid = uuid.uuid4().hex[:8]
    creds = {
        "username": f"{role.value}_{uid}",
        "email": f"{role.value}_{uid}@example.com",
        "password": "TestPass123!",
        "role": role.value,
    }
    r = await client.post("/api/v1/auth/register", json=creds)
    # 400 = user already exists (acceptable without per-test cleanup)
    # 409 = email already exists (same reason)
    if r.status_code not in (200, 201, 400, 409):
        r.raise_for_status()

    # Login - this should always succeed if registration succeeded or user exists
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
