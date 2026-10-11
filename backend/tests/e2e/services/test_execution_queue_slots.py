import time
from uuid import uuid4

import pytest
import redis.asyncio as redis
import structlog

from app.core.metrics.queue import QueueMetrics
from app.services.execution_queue import ExecutionQueueService, _user_key
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.redis]


@pytest.fixture
def queue(redis_client: redis.Redis, test_settings: Settings) -> ExecutionQueueService:
    logger = structlog.get_logger("test.execution_queue")
    return ExecutionQueueService(redis_client, logger, QueueMetrics(test_settings))


async def test_user_slots_stop_at_the_limit_and_free_on_release(queue: ExecutionQueueService) -> None:
    user = f"u-{uuid4().hex}"
    e1, e2, e3 = (f"{name}-{user}" for name in ("e1", "e2", "e3"))

    assert await queue.reserve_user_slot(user, e1, 2)
    assert await queue.reserve_user_slot(user, e2, 2)
    assert not await queue.reserve_user_slot(user, e3, 2)

    await queue.release_user_slot(e1)
    assert await queue.reserve_user_slot(user, e3, 2)


async def test_expired_user_slots_do_not_count(queue: ExecutionQueueService, redis_client: redis.Redis) -> None:
    user = f"u-{uuid4().hex}"
    await redis_client.zadd(_user_key(user), {"stale": time.time() - 1})

    assert await queue.reserve_user_slot(user, "fresh", 1)
    assert await redis_client.zrange(_user_key(user), 0, -1) == ["fresh"]


async def test_scheduling_drops_expired_running_slots(queue: ExecutionQueueService, redis_client: redis.Redis) -> None:
    suffix = uuid4().hex
    running, pending = f"test:running:{suffix}", f"test:pending:{suffix}"
    now = time.time()
    await redis_client.zadd(running, {"lost-release": now - 10})
    await redis_client.zadd(pending, {"next": now})

    script = await queue._get_schedule_script()
    result = await script(keys=[running, pending], args=[1, now, now + 60])

    assert result[0] == "next"
    assert await redis_client.zrange(running, 0, -1, withscores=True) == [("next", now + 60)]


async def test_scheduling_waits_while_live_slots_fill_the_limit(
    queue: ExecutionQueueService, redis_client: redis.Redis
) -> None:
    suffix = uuid4().hex
    running, pending = f"test:running:{suffix}", f"test:pending:{suffix}"
    now = time.time()
    await redis_client.zadd(running, {"busy": now + 100})
    await redis_client.zadd(pending, {"next": now})

    script = await queue._get_schedule_script()

    assert await script(keys=[running, pending], args=[1, now, now + 60]) is None
    assert await redis_client.zcard(pending) == 1
