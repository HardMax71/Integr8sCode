import logging
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database
from app.core.metrics import DatabaseMetrics, EventMetrics
from app.events.core import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.idempotency_manager import IdempotencyConfig, IdempotencyManager
from app.services.idempotency.redis_repository import RedisIdempotencyRepository
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers.cleanup import cleanup_db_and_redis

_test_logger = logging.getLogger("test.integration")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> AsyncGenerator[None, None]:
    """Clean DB and Redis before each integration test.

    Only pre-test cleanup - post-test cleanup causes event loop issues
    when SSE/streaming tests hold connections across loop boundaries.
    """
    await cleanup_db_and_redis(db, redis_client)
    yield
    # No post-test cleanup to avoid "Event loop is closed" errors


# ===== DI-based fixtures for integration tests =====


@pytest_asyncio.fixture
async def schema_registry(scope: AsyncContainer) -> SchemaRegistryManager:
    """Provide SchemaRegistryManager via DI."""
    return await scope.get(SchemaRegistryManager)


@pytest_asyncio.fixture
async def event_metrics(scope: AsyncContainer) -> EventMetrics:
    """Provide EventMetrics via DI."""
    return await scope.get(EventMetrics)


@pytest_asyncio.fixture
async def database_metrics(scope: AsyncContainer) -> DatabaseMetrics:
    """Provide DatabaseMetrics via DI."""
    return await scope.get(DatabaseMetrics)


# ===== Config fixtures =====


@pytest.fixture
def consumer_config(test_settings: Settings) -> ConsumerConfig:
    """Provide a unique ConsumerConfig for each test.

    Defaults for integration tests:
    - enable_auto_commit=True: Commit offsets automatically for simpler test cleanup
    - auto_offset_reset="earliest": Read all messages from start (default in ConsumerConfig)
    """
    return ConsumerConfig(
        bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-consumer-{uuid.uuid4().hex[:6]}",
        enable_auto_commit=True,
    )


@pytest_asyncio.fixture
async def sse_redis_bus(redis_client: redis.Redis) -> SSERedisBus:
    """Provide SSERedisBus with unique prefixes for test isolation."""
    suffix = uuid.uuid4().hex[:6]
    return SSERedisBus(
        redis_client,
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
        logger=_test_logger,
    )


@pytest_asyncio.fixture
async def idempotency_manager(
    redis_client: redis.Redis, database_metrics: DatabaseMetrics
) -> AsyncGenerator[IdempotencyManager, None]:
    """Provide IdempotencyManager with unique prefix for test isolation."""
    prefix = f"idemp:{uuid.uuid4().hex[:6]}"
    cfg = IdempotencyConfig(
        key_prefix=prefix,
        default_ttl_seconds=3600,
        processing_timeout_seconds=5,
        enable_result_caching=True,
        max_result_size_bytes=1024,
    )
    repo = RedisIdempotencyRepository(redis_client, key_prefix=prefix)
    yield IdempotencyManager(repository=repo, logger=_test_logger, metrics=database_metrics, config=cfg)
