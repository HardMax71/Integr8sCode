import os
import uuid
from collections.abc import Iterable
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database
from app.domain.enums.execution import QueuePriority
from app.domain.events.typed import EventMetadata, ExecutionRequestedEvent
from app.main import create_app
from app.settings import Settings
from dishka import AsyncContainer
from fastapi import FastAPI
from httpx import ASGITransport


def _get_worker_num() -> int:
    """Get numeric pytest-xdist worker ID for Redis DB selection (0-15)."""
    wid = os.environ.get("PYTEST_XDIST_WORKER", "main")
    return 0 if wid == "main" else int(wid.removeprefix("gw"))


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Test settings with per-worker Redis DB isolation.

    - MongoDB: Shared database, tests use UUIDs for entity isolation
    - Kafka: Tests with consumers use xdist_group markers for serial execution
    - Redis: Per-worker DB number (0-15) to avoid key collisions
    """
    base = Settings(_env_file=".env.test")
    return base.model_copy(update={"REDIS_DB": _get_worker_num() % 16})


# ===== App fixture =====
@pytest_asyncio.fixture(scope="session")
async def app(test_settings: Settings) -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with test settings and run lifespan.

    Session-scoped to avoid Pydantic schema validator memory issues when
    FastAPI recreates OpenAPI schemas hundreds of times with pytest-xdist.

    Uses lifespan_context to trigger startup/shutdown events, which initializes
    Beanie, metrics, and other services through the normal DI flow.

    Note: Database is shared across all tests and workers. Tests use unique IDs
    so they don't conflict. Periodic cleanup of stale test data can be done
    outside of tests if needed.
    """
    application = create_app(settings=test_settings)

    async with application.router.lifespan_context(application):
        yield application


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


@pytest_asyncio.fixture
async def scope(app: FastAPI) -> AsyncGenerator[AsyncContainer, None]:
    """Create a Dishka scope for resolving dependencies in tests."""
    container: AsyncContainer = app.state.dishka_container
    async with container() as s:
        yield s


@pytest_asyncio.fixture
async def db(scope: AsyncContainer) -> AsyncGenerator[Database, None]:
    database: Database = await scope.get(Database)
    yield database


@pytest_asyncio.fixture
async def redis_client(scope: AsyncContainer) -> AsyncGenerator[redis.Redis, None]:
    # Dishka's RedisProvider handles cleanup when scope exits
    yield await scope.get(redis.Redis)


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
        # 200: created, 400: username exists, 409: email exists - all OK to proceed to login
        if r.status_code not in (200, 400, 409):
            pytest.fail(f"Cannot create {role} (status {r.status_code}): {r.text}")

        login_resp = await c.post("/api/v1/auth/login", data={
            "username": username,
            "password": password,
        })
        login_resp.raise_for_status()

        login_data = login_resp.json()
        csrf = login_data.get("csrf_token")
        if not csrf:
            await c.aclose()
            pytest.fail(
                f"Login succeeded but csrf_token missing or empty for {role} '{username}'. "
                f"Response: {login_resp.text}"
            )

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


# ===== Event factories =====


def make_execution_requested_event(
    *,
    execution_id: str | None = None,
    script: str = "print('hello')",
    language: str = "python",
    language_version: str = "3.11",
    runtime_image: str = "python:3.11-slim",
    runtime_command: Iterable[str] = ("python",),
    runtime_filename: str = "main.py",
    timeout_seconds: int = 5,
    cpu_limit: str = "100m",
    memory_limit: str = "128Mi",
    cpu_request: str = "50m",
    memory_request: str = "64Mi",
    priority: QueuePriority = QueuePriority.NORMAL,
    service_name: str = "tests",
    service_version: str = "1.0.0",
    user_id: str | None = None,
) -> ExecutionRequestedEvent:
    """Factory for ExecutionRequestedEvent with sensible defaults.

    Override any field via keyword args. If no execution_id is provided, a random one is generated.
    """
    if execution_id is None:
        execution_id = f"exec-{uuid.uuid4().hex[:8]}"

    metadata = EventMetadata(service_name=service_name, service_version=service_version, user_id=user_id)
    return ExecutionRequestedEvent(
        execution_id=execution_id,
        aggregate_id=execution_id,  # Match production: aggregate_id == execution_id for execution events
        script=script,
        language=language,
        language_version=language_version,
        runtime_image=runtime_image,
        runtime_command=list(runtime_command),
        runtime_filename=runtime_filename,
        timeout_seconds=timeout_seconds,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        cpu_request=cpu_request,
        memory_request=memory_request,
        priority=priority,
        metadata=metadata,
    )
