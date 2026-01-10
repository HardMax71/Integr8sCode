import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database
from app.main import create_app
from app.settings import Settings
from dishka import AsyncContainer
from fastapi import FastAPI
from httpx import ASGITransport

# ===== Worker-specific isolation for pytest-xdist =====
_WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER", "gw0")


# ===== Settings fixture =====
@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Provide test settings with a unique Kafka topic prefix for isolation."""
    # _env_file is a pydantic-settings init kwarg
    base = Settings(_env_file=".env.test", _env_file_encoding="utf-8")
    session_id = uuid.uuid4().hex[:8]
    base_prefix = f"{base.KAFKA_TOPIC_PREFIX.rstrip('.')}."
    worker_num = sum(_WORKER_ID.encode()) % 16
    unique_prefix = f"{base_prefix}{session_id}.{_WORKER_ID}."
    return base.model_copy(
        update={
            "DATABASE_NAME": f"integr8scode_test_{session_id}_{_WORKER_ID}",
            "REDIS_DB": worker_num % 16,
            "KAFKA_GROUP_SUFFIX": f"{session_id}.{_WORKER_ID}",
            "SCHEMA_SUBJECT_PREFIX": f"test.{session_id}.{_WORKER_ID}.",
            "KAFKA_TOPIC_PREFIX": unique_prefix,
            "OTEL_EXPORTER_OTLP_ENDPOINT": None,  # Disable OTel metrics export in tests
            "ENABLE_TRACING": False,  # Fully disable tracing/metrics in tests
        }
    )


# ===== App fixture =====
@pytest_asyncio.fixture(scope="session")
async def app(test_settings: Settings) -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with test settings.

    Session-scoped to avoid Pydantic schema validator memory issues when
    FastAPI recreates OpenAPI schemas hundreds of times with pytest-xdist.
    """
    application = create_app(settings=test_settings)

    yield application

    if hasattr(application.state, "dishka_container"):
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
    database: Database = await scope.get(Database)
    yield database


@pytest_asyncio.fixture
async def redis_client(scope: AsyncContainer) -> AsyncGenerator[redis.Redis, None]:
    # Don't close here - Dishka's RedisProvider handles cleanup when scope exits
    client: redis.Redis = await scope.get(redis.Redis)
    yield client


# ===== Authenticated client fixtures =====
# Return httpx.AsyncClient with CSRF header pre-set. Just use test_user.post(...) directly.


async def _create_authenticated_client(
    app: FastAPI, username: str, email: str, password: str, role: str
) -> httpx.AsyncClient:
    """Create and return an authenticated client with CSRF header set."""
    c = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        timeout=30.0,
        follow_redirects=True,
    )
    try:
        r = await c.post("/api/v1/auth/register", json={
            "username": username,
            "email": email,
            "password": password,
            "role": role,
        })
        if r.status_code not in (200, 201, 400):
            pytest.fail(f"Cannot create {role} (status {r.status_code}): {r.text}")

        login_resp = await c.post("/api/v1/auth/login", data={
            "username": username,
            "password": password,
        })
        login_resp.raise_for_status()
        csrf = login_resp.json().get("csrf_token", "")
        c.headers["X-CSRF-Token"] = csrf
        return c
    except Exception:
        await c.aclose()
        raise


@pytest_asyncio.fixture
async def test_user(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Authenticated user client. CSRF header is set automatically."""
    uid = uuid.uuid4().hex[:8]
    c = await _create_authenticated_client(
        app,
        username=f"test_user_{uid}",
        email=f"test_user_{uid}@example.com",
        password="TestPass123!",
        role="user",
    )
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def test_admin(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Authenticated admin client. CSRF header is set automatically."""
    uid = uuid.uuid4().hex[:8]
    c = await _create_authenticated_client(
        app,
        username=f"admin_user_{uid}",
        email=f"admin_user_{uid}@example.com",
        password="AdminPass123!",
        role="admin",
    )
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def another_user(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Another authenticated user client (for multi-user tests)."""
    uid = uuid.uuid4().hex[:8]
    c = await _create_authenticated_client(
        app,
        username=f"test_user_{uid}",
        email=f"test_user_{uid}@example.com",
        password="TestPass123!",
        role="user",
    )
    yield c
    await c.aclose()
