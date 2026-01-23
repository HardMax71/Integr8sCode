import asyncio
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
from scripts.create_topics import create_topics

# ===== Worker-specific identifiers for pytest-xdist =====
# Used only for Kafka consumer group isolation (technical requirement).
# Database isolation is NOT needed - tests use unique IDs (UUIDs) for all entities.
_RUN_ID = os.environ.get("TEST_RUN_ID") or uuid.uuid4().hex[:8]
_WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
_WORKER_NUM = int(_WORKER_ID.removeprefix("gw") or "0")
_ISOLATION_KEY = f"{_RUN_ID}_{_WORKER_ID}"


# ===== Pytest hooks =====
@pytest.hookimpl(trylast=True)
def pytest_configure() -> None:
    """Create Kafka topics once in master process before xdist workers spawn."""
    # PYTEST_XDIST_WORKER is only set in workers, not master
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    try:
        asyncio.run(create_topics(Settings(_env_file=".env.test")))
    except Exception:
        pass  # Kafka unavailable (unit tests)


# ===== Settings fixture =====
@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Provide test settings - single shared database, per-worker Kafka groups.

    Tests use unique IDs (UUIDs) for all entities:
      - Users: test_user_{uuid}@example.com
      - Executions: UUID-based execution_id
      - Events: UUID-based event_id

    This means tests don't conflict even when sharing a database.

    What's SHARED (all workers + external services like k8s-worker):
      - DATABASE_NAME: From .env.test (integr8scode_db)
      - KAFKA_TOPIC_PREFIX: Topics created once by CI/scripts
      - SCHEMA_SUBJECT_PREFIX: Schemas shared across workers

    What's per-worker (technical requirements):
      - KAFKA_GROUP_SUFFIX: Each worker needs unique consumer groups
      - REDIS_DB: Avoid key collisions for rate limiting, caching

    This allows:
      - Parallel test execution with -n auto
      - E2E tests with real workers (same database)
      - No duplicate test_settings fixtures
    """
    base = Settings(_env_file=".env.test")
    # Deterministic Redis DB: worker number + ASCII sum of RUN_ID (no hash randomization)
    redis_db = (_WORKER_NUM + sum(ord(c) for c in _RUN_ID)) % 16
    return base.model_copy(
        update={
            # Per-worker isolation for technical reasons only
            "REDIS_DB": redis_db,
            "KAFKA_GROUP_SUFFIX": _ISOLATION_KEY,
        }
    )


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
