import asyncio
from uuid import uuid4
from tests.helpers.eventually import eventually
import pytest

from app.core.metrics.events import EventMetrics
from app.events.core import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from tests.helpers import make_execution_requested_event
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.schemas_pydantic.sse import RedisSSEMessage
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.redis]


@pytest.mark.asyncio
async def test_router_bridges_to_redis(redis_client) -> None:  # type: ignore[valid-type]
    settings = Settings()
    suffix = uuid4().hex[:6]
    bus = SSERedisBus(
        redis_client,
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
    )
    router = SSEKafkaRedisBridge(
        schema_registry=SchemaRegistryManager(),
        settings=settings,
        event_metrics=EventMetrics(),
        sse_bus=bus,
    )
    disp = EventDispatcher()
    router._register_routing_handlers(disp)

    # Open Redis subscription for our execution id
    execution_id = f"e-{uuid4().hex[:8]}"
    subscription = await bus.open_subscription(execution_id)

    ev = make_execution_requested_event(execution_id=execution_id)
    handler = disp.get_handlers(ev.event_type)[0]
    await handler(ev)

    async def _recv():
        m = await subscription.get(RedisSSEMessage)
        assert m is not None
        return m

    msg = await eventually(_recv, timeout=2.0, interval=0.05)
    assert str(msg.event_type) == str(ev.event_type)


@pytest.mark.asyncio
async def test_router_start_and_stop(redis_client) -> None:  # type: ignore[valid-type]
    settings = Settings()
    settings.SSE_CONSUMER_POOL_SIZE = 1
    suffix = uuid4().hex[:6]
    router = SSEKafkaRedisBridge(
        schema_registry=SchemaRegistryManager(),
        settings=settings,
        event_metrics=EventMetrics(),
        sse_bus=SSERedisBus(
            redis_client,
            exec_prefix=f"sse:exec:{suffix}:",
            notif_prefix=f"sse:notif:{suffix}:",
        ),
    )

    await router.start()
    stats = router.get_stats()
    assert stats["num_consumers"] == 1
    await router.stop()
    assert router.get_stats()["num_consumers"] == 0
    # idempotent start/stop
    await router.start()
    await router.start()
    await router.stop()
    await router.stop()
