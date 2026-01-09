import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, TypedDict

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from dishka import AsyncContainer
from fastapi import FastAPI
from httpx import ASGITransport

from app.core.database_context import Database
from app.main import create_app
from app.settings import Settings


class UserCredentials(TypedDict):
    """Type for test user/admin credentials returned by fixtures."""

    username: str
    email: str
    password: str
    role: str
    csrf_token: str
    headers: dict[str, str]

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
    client: redis.Redis = await scope.get(redis.Redis)
    try:
        yield client
    finally:
        await client.aclose()


# ===== HTTP helpers (auth) =====
async def _http_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    data = {"username": username, "password": password}
    resp = await client.post("/api/v1/auth/login", data=data)
    resp.raise_for_status()
    json_data: dict[str, str] = resp.json()
    return json_data.get("csrf_token", "")


@pytest_asyncio.fixture
async def test_user(client: httpx.AsyncClient) -> UserCredentials:
    """Function-scoped authenticated user."""
    uid = uuid.uuid4().hex[:8]
    username = f"test_user_{uid}"
    email = f"test_user_{uid}@example.com"
    password = "TestPass123!"
    role = "user"
    r = await client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
        "role": role,
    })
    if r.status_code not in (200, 201, 400):
        pytest.fail(f"Cannot create test user (status {r.status_code}): {r.text}")
    csrf = await _http_login(client, username, password)
    return {
        "username": username,
        "email": email,
        "password": password,
        "role": role,
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf},
    }


@pytest_asyncio.fixture
async def test_admin(client: httpx.AsyncClient) -> UserCredentials:
    """Function-scoped authenticated admin."""
    uid = uuid.uuid4().hex[:8]
    username = f"admin_user_{uid}"
    email = f"admin_user_{uid}@example.com"
    password = "AdminPass123!"
    role = "admin"
    r = await client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
        "role": role,
    })
    if r.status_code not in (200, 201, 400):
        pytest.fail(f"Cannot create test admin (status {r.status_code}): {r.text}")
    csrf = await _http_login(client, username, password)
    return {
        "username": username,
        "email": email,
        "password": password,
        "role": role,
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf},
    }


@pytest_asyncio.fixture
async def another_user(client: httpx.AsyncClient) -> UserCredentials:
    """Function-scoped another authenticated user."""
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "TestPass123!"
    role = "user"
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "role": role,
        },
    )
    csrf = await _http_login(client, username, password)
    return {
        "username": username,
        "email": email,
        "password": password,
        "role": role,
        "csrf_token": csrf,
        "headers": {"X-CSRF-Token": csrf},
    }
