import logging
from uuid import uuid4

import pytest
import redis.asyncio as redis
from app.core.metrics.events import EventMetrics
from app.events.core import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.schemas_pydantic.sse import RedisSSEMessage
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings

from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.redis]

_test_logger = logging.getLogger("test.services.sse.partitioned_event_router_integration")


@pytest.mark.asyncio
async def test_router_bridges_to_redis(redis_client: redis.Redis, test_settings: Settings) -> None:
    suffix = uuid4().hex[:6]
    bus = SSERedisBus(
        redis_client,
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
        logger=_test_logger,
    )
    router = SSEKafkaRedisBridge(
        schema_registry=SchemaRegistryManager(settings=test_settings, logger=_test_logger),
        settings=test_settings,
        event_metrics=EventMetrics(test_settings),
        sse_bus=bus,
        logger=_test_logger,
    )
    disp = EventDispatcher(logger=_test_logger)
    router._register_routing_handlers(disp)

    # Open Redis subscription for our execution id
    execution_id = f"e-{uuid4().hex[:8]}"
    subscription = await bus.open_subscription(execution_id)

    ev = make_execution_requested_event(execution_id=execution_id)
    handler = disp.get_handlers(ev.event_type)[0]
    await handler(ev)

    async def _recv() -> RedisSSEMessage:
        m = await subscription.get(RedisSSEMessage)
        assert m is not None
        return m

    msg = await eventually(_recv, timeout=2.0, interval=0.05)
    assert str(msg.event_type) == str(ev.event_type)


@pytest.mark.asyncio
async def test_router_start_and_stop(redis_client: redis.Redis, test_settings: Settings) -> None:
    test_settings.SSE_CONSUMER_POOL_SIZE = 1
    suffix = uuid4().hex[:6]
    router = SSEKafkaRedisBridge(
        schema_registry=SchemaRegistryManager(settings=test_settings, logger=_test_logger),
        settings=test_settings,
        event_metrics=EventMetrics(test_settings),
        sse_bus=SSERedisBus(
            redis_client,
            exec_prefix=f"sse:exec:{suffix}:",
            notif_prefix=f"sse:notif:{suffix}:",
            logger=_test_logger,
        ),
        logger=_test_logger,
    )

    await router.__aenter__()
    stats = router.get_stats()
    assert stats["num_consumers"] == 1
    await router.aclose()
    assert router.get_stats()["num_consumers"] == 0
    # idempotent start/stop
    await router.__aenter__()
    await router.__aenter__()
    await router.aclose()
    await router.aclose()
