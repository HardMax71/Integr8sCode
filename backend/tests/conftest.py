import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Callable, Awaitable

import httpx
import pytest
import pytest_asyncio
from dishka import AsyncContainer
from dotenv import load_dotenv
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorDatabase
import redis.asyncio as redis

# Load test environment variables BEFORE any app imports
test_env_path = Path(__file__).parent.parent / ".env.test"
if test_env_path.exists():
    load_dotenv(test_env_path, override=True)

# IMPORTANT: avoid importing app.main at module import time because it
# constructs the FastAPI app immediately (reading settings from .env).
# We import lazily inside the fixture after test env vars are set.
from tests.helpers.eventually import eventually as _eventually
# DO NOT import any app.* modules at import time here, as it would
# construct global singletons (logger, settings) before we set test env.


# Let pytest-asyncio handle the event loop
# The asyncio_default_fixture_loop_scope = "session" in pyproject.toml handles this
# Motor and Redis now explicitly bind to the current loop in providers.py


# Note: pytest-asyncio (auto mode) manages event loops per test.


# ===== Early, host-friendly defaults (applied at import time) =====
# Ensure tests connect to localhost services when run outside Docker.
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("ENABLE_TRACING", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")

# Force localhost endpoints to avoid Docker DNS names like 'mongo'
# Do not override if MONGODB_URL is already provided in the environment.
if "MONGODB_URL" not in os.environ:
    from urllib.parse import quote_plus
    user = os.environ.get("MONGO_ROOT_USER", "root")
    pwd = os.environ.get("MONGO_ROOT_PASSWORD", "rootpassword")
    host = os.environ.get("MONGODB_HOST", "127.0.0.1")
    port = os.environ.get("MONGODB_PORT", "27017")
    try:
        u = quote_plus(user)
        p = quote_plus(pwd)
    except Exception:
        u = user
        p = pwd
    os.environ["MONGODB_URL"] = (
        f"mongodb://{u}:{p}@{host}:{port}/?authSource=admin&authMechanism=SCRAM-SHA-256"
    )
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("SCHEMA_REGISTRY_URL", "http://localhost:8081")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-32chars!!")


# ===== Global test environment (reinforce and isolation) =====
def _compute_worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "gw0")


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> None:
    # Core toggles
    os.environ.setdefault("TESTING", "true")
    os.environ.setdefault("ENABLE_TRACING", "false")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
    os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")

    # External services - force localhost when running tests on host
    os.environ["MONGODB_URL"] = os.environ.get(
        "MONGODB_URL",
        "mongodb://root:rootpassword@localhost:27017/?authSource=admin",
    )
    os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    os.environ.setdefault("REDIS_HOST", "localhost")
    os.environ.setdefault("REDIS_PORT", "6379")
    os.environ.setdefault("SCHEMA_REGISTRY_URL", "http://localhost:8081")
    os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-32chars!!")

    # Isolation identifiers
    session_id = os.environ.get("PYTEST_SESSION_ID") or uuid.uuid4().hex[:8]
    worker_id = _compute_worker_id()
    os.environ["PYTEST_SESSION_ID"] = session_id

    # Unique project name -> database name will be f"{PROJECT_NAME}_test"
    os.environ["PROJECT_NAME"] = f"integr8scode_{session_id}_{worker_id}"

    # Try to distribute Redis DBs across workers (0-15 by default). Fallback to 0.
    try:
        worker_num = int(worker_id[2:]) if worker_id.startswith("gw") else 0
        os.environ["REDIS_DB"] = str(worker_num % 16)
    except Exception:
        os.environ.setdefault("REDIS_DB", "0")

    # Use a single shared test topic prefix for all tests
    # This avoids creating unique topics per worker/session
    os.environ.setdefault("KAFKA_TOPIC_PREFIX", "test.")
    try:
        from app.domain.enums.kafka import KafkaTopic  # local import to avoid import-time side effects

        def _prefixed_str(self: object) -> str:  # type: ignore[no-redef]
            prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "")
            # Enum instance has .value
            val = getattr(self, "value", None)
            return f"{prefix}{val}" if isinstance(val, str) else str(val)

        # Patch string conversion so all producers/consumers use prefixed topics in tests
        KafkaTopic.__str__ = _prefixed_str  # type: ignore[assignment]
        KafkaTopic.__repr__ = _prefixed_str  # type: ignore[assignment]
        # Also patch EventBus topic name
        try:
            from app.services.event_bus import EventBus

            _orig_init = EventBus.__init__

            def _init_with_prefix(self) -> None:  # type: ignore[no-redef]
                _orig_init(self)
                prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "")
                self._topic = f"{prefix}{self._topic}"

            EventBus.__init__ = _init_with_prefix  # type: ignore[assignment]
        except Exception:
            pass
    except Exception:
        # If topic patching fails, tests still run with unique consumer groups
        pass

    # Keep unique consumer groups per worker to avoid conflicts
    # But all workers will consume from the same test topics
    os.environ.setdefault("KAFKA_GROUP_SUFFIX", f"{session_id}.{worker_id}")
    try:
        from app.domain.enums.kafka import GroupId  # local import

        def _group_with_suffix(self: object) -> str:  # type: ignore[no-redef]
            suffix = os.environ.get("KAFKA_GROUP_SUFFIX", "")
            val = getattr(self, "value", None)
            base = str(val) if not isinstance(val, str) else val
            return f"{base}.{suffix}" if suffix else base

        GroupId.__str__ = _group_with_suffix  # type: ignore[assignment]
        GroupId.__repr__ = _group_with_suffix  # type: ignore[assignment]
    except Exception:
        pass


# ===== App creation for tests =====
def create_test_app():
    """Create the FastAPI app for testing."""
    # Clear settings cache to ensure .env.test values are used
    from app.settings import get_settings
    get_settings.cache_clear()
    
    from importlib import import_module
    mainmod = import_module("app.main")
    return getattr(mainmod, "create_app")()


# ===== App without lifespan for tests =====
@pytest_asyncio.fixture(scope="function")
async def app():
    """Create FastAPI app for the function without starting lifespan."""
    application = create_test_app()
    # Don't use LifespanManager - it tries to start Kafka consumers etc which hang in tests
    
    yield application
    
    # Clean up Dishka container to stop background tasks
    if hasattr(application.state, 'dishka_container'):
        container: AsyncContainer = application.state.dishka_container
        await container.close()


@pytest_asyncio.fixture(scope="function")
async def app_container(app):  # type: ignore[valid-type]
    """Expose the Dishka container attached to the app."""
    container: AsyncContainer = app.state.dishka_container  # type: ignore[attr-defined]
    return container


## No prewarm: resources are created within the test's event loop


# ===== Client (function-scoped for clean cookies per test) =====
@pytest_asyncio.fixture(scope="function")
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:  # type: ignore[valid-type]
    # Use httpx with ASGI app directly
    # The app fixture already handles lifespan via LifespanManager
    # Use HTTPS scheme so 'Secure' cookies set by the app (access_token, csrf_token)
    # are accepted and sent by the client during tests.
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        timeout=30.0,
        follow_redirects=True
    ) as c:
        yield c


# ===== Request-scope accessor =====
@asynccontextmanager
async def _container_scope(container: AsyncContainer):
    async with container() as scope:  # type: ignore[misc]
        yield scope


@pytest_asyncio.fixture(scope="function")
async def scope(app_container: AsyncContainer):  # type: ignore[valid-type]
    async with _container_scope(app_container) as s:
        yield s


@pytest_asyncio.fixture(scope="function")
async def db(scope) -> AsyncGenerator[AsyncIOMotorDatabase, None]:  # type: ignore[valid-type]
    database: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)
    yield database


@pytest_asyncio.fixture(scope="function")
async def redis_client(scope) -> AsyncGenerator[redis.Redis, None]:  # type: ignore[valid-type]
    client: redis.Redis = await scope.get(redis.Redis)
    yield client


# ===== Per-test cleanup =====
@pytest_asyncio.fixture(scope="function", autouse=True)
async def _cleanup(db: AsyncIOMotorDatabase, redis_client: redis.Redis):
    # Pre-test: ensure clean state
    collections = await db.list_collection_names()
    for name in collections:
        if not name.startswith("system."):
            await db.drop_collection(name)
    await redis_client.flushdb()
    
    yield
    
    # Post-test: cleanup for next test
    collections = await db.list_collection_names()
    for name in collections:
        if not name.startswith("system."):
            await db.drop_collection(name)
    await redis_client.flushdb()


# ===== HTTP helpers (auth) =====
async def _http_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    data = {"username": username, "password": password}
    resp = await client.post("/api/v1/auth/login", data=data)
    resp.raise_for_status()
    return resp.json().get("csrf_token", "")


# Session-scoped shared users for convenience
@pytest.fixture(scope="session")
def shared_user_credentials():
    uid = os.environ.get("PYTEST_SESSION_ID", uuid.uuid4().hex[:8])
    return {
        "username": f"test_user_{uid}",
        "email": f"test_user_{uid}@example.com",
        "password": "TestPass123!",
        "role": "user",
    }


@pytest.fixture(scope="session")
def shared_admin_credentials():
    uid = os.environ.get("PYTEST_SESSION_ID", uuid.uuid4().hex[:8])
    return {
        "username": f"admin_user_{uid}",
        "email": f"admin_user_{uid}@example.com",
        "password": "AdminPass123!",
        "role": "admin",
    }


@pytest_asyncio.fixture(scope="function")
async def shared_user(client: httpx.AsyncClient, shared_user_credentials):
    creds = shared_user_credentials
    # Always attempt to register; DB is wiped after each test
    r = await client.post("/api/v1/auth/register", json=creds)
    if r.status_code not in (200, 201, 400):
        pytest.skip(f"Cannot create shared user (status {r.status_code}).")
    csrf = await _http_login(client, creds["username"], creds["password"])
    return {**creds, "csrf_token": csrf, "headers": {"X-CSRF-Token": csrf}}


@pytest_asyncio.fixture(scope="function")
async def shared_admin(client: httpx.AsyncClient, shared_admin_credentials):
    creds = shared_admin_credentials
    r = await client.post("/api/v1/auth/register", json=creds)
    if r.status_code not in (200, 201, 400):
        pytest.skip(f"Cannot create shared admin (status {r.status_code}).")
    csrf = await _http_login(client, creds["username"], creds["password"])
    return {**creds, "csrf_token": csrf, "headers": {"X-CSRF-Token": csrf}}


@pytest_asyncio.fixture(scope="function")
async def another_user(client: httpx.AsyncClient):
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "TestPass123!"
    await client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
        "role": "user",
    })
    csrf = await _http_login(client, username, password)
    return {"username": username, "email": email, "password": password, "csrf_token": csrf, "headers": {"X-CSRF-Token": csrf}}


@pytest_asyncio.fixture(scope="function")
async def make_user(client: httpx.AsyncClient) -> Callable[[str, str, str], Awaitable[dict[str, str]]]:
    async def _create(username: str, email: str, password: str, *, admin: bool = False) -> dict[str, str]:
        payload = {"username": username, "email": email, "password": password, "role": "admin" if admin else "user"}
        r = await client.post("/api/v1/auth/register", json=payload)
        if r.status_code not in (200, 201, 400):
            pytest.skip(f"Cannot create user via API (status {r.status_code}).")
        return payload
    return _create


@pytest_asyncio.fixture(scope="function")
async def login_user(client: httpx.AsyncClient) -> Callable[[str, str], Awaitable[str]]:
    async def _login(username: str, password: str) -> str:
        return await _http_login(client, username, password)
    return _login


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "performance: mark test as performance test")
    config.addinivalue_line("markers", "load: mark test as load/property test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "kafka: mark test as requiring Kafka")
    config.addinivalue_line("markers", "mongodb: mark test as requiring MongoDB")
    config.addinivalue_line("markers", "k8s: mark test as requiring Kubernetes cluster")


@pytest_asyncio.fixture(scope="function")
async def producer(scope):  # type: ignore[valid-type]
    # Lazy import to avoid early settings initialization
    from app.events.core import UnifiedProducer
    return await scope.get(UnifiedProducer)


@pytest.fixture(scope="function")
def send_event(producer):  # type: ignore[valid-type]
    from app.infrastructure.kafka.events.base import BaseEvent  # noqa: F401

    async def _send(ev):  # noqa: ANN001
        await producer.produce(ev)

    return _send


@pytest.fixture(scope="function")
def eventually():
    return _eventually
