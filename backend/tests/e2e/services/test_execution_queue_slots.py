import time
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import redis.asyncio as redis
import structlog
from opentelemetry import trace

from app.services.execution_queue import ExecutionQueueService, _user_key

pytestmark = [pytest.mark.e2e]


@pytest.fixture
def queue(redis_client: redis.Redis) -> ExecutionQueueService:
    logger = structlog.get_logger("test.execution_queue")
    return ExecutionQueueService(redis_client, logger, trace.NoOpTracer())


@pytest.fixture
async def scratch_keys(redis_client: redis.Redis) -> AsyncIterator[tuple[str, str]]:
    suffix = uuid4().hex
    running, pending = f"test:running:{suffix}", f"test:pending:{suffix}"
    yield running, pending
    await redis_client.delete(running, pending)


async def test_user_slots_stop_at_the_limit_and_free_on_release(queue: ExecutionQueueService) -> None:
    user = f"u-{uuid4().hex}"
    e1, e2, e3 = (f"{name}-{user}" for name in ("e1", "e2", "e3"))

    assert await queue.reserve_user_slot(user, e1, 2)
    assert await queue.reserve_user_slot(user, e2, 2)
    assert not await queue.reserve_user_slot(user, e3, 2)

    await queue.release_user_slot(e1)
    assert await queue.reserve_user_slot(user, e3, 2)
    for execution_id in (e2, e3):
        await queue.release_user_slot(execution_id)


async def test_expired_user_slots_do_not_count(queue: ExecutionQueueService, redis_client: redis.Redis) -> None:
    user = f"u-{uuid4().hex}"
    await redis_client.zadd(_user_key(user), {"stale": time.time() - 1})

    fresh = f"fresh-{user}"
    assert await queue.reserve_user_slot(user, fresh, 1)
    assert await redis_client.zrange(_user_key(user), 0, -1) == [fresh]
    await queue.release_user_slot(fresh)


async def test_scheduling_drops_expired_running_slots(
    queue: ExecutionQueueService, redis_client: redis.Redis, scratch_keys: tuple[str, str]
) -> None:
    running, pending = scratch_keys
    now = time.time()
    await redis_client.zadd(running, {"lost-release": now - 10})
    await redis_client.zadd(pending, {"next": now})

    script = queue._schedule_script
    result = await script(keys=[running, pending], args=[1, now, now + 60])

    assert result[0] == "next"
    assert await redis_client.zrange(running, 0, -1, withscores=True) == [("next", pytest.approx(now + 60))]


async def test_scheduling_waits_while_live_slots_fill_the_limit(
    queue: ExecutionQueueService, redis_client: redis.Redis, scratch_keys: tuple[str, str]
) -> None:
    running, pending = scratch_keys
    now = time.time()
    await redis_client.zadd(running, {"busy": now + 100})
    await redis_client.zadd(pending, {"next": now})

    script = queue._schedule_script

    assert await script(keys=[running, pending], args=[1, now, now + 60]) is None
    assert await redis_client.zcard(pending) == 1
