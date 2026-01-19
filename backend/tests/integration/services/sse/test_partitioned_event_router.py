import asyncio
import logging
from uuid import uuid4

import pytest
from app.core.metrics import EventMetrics
from app.events.core import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.schemas_pydantic.sse import RedisSSEMessage
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.redis]

_test_logger = logging.getLogger("test.services.sse.partitioned_event_router_integration")


@pytest.mark.asyncio
async def test_router_bridges_to_redis(
    sse_redis_bus: SSERedisBus,
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    test_settings: Settings,
) -> None:
    router = SSEKafkaRedisBridge(
        schema_registry=schema_registry,
        settings=test_settings,
        event_metrics=event_metrics,
        sse_bus=sse_redis_bus,
        logger=_test_logger,
    )
    disp = EventDispatcher(logger=_test_logger)
    router._register_routing_handlers(disp)

    # Open Redis subscription for our execution id
    execution_id = f"e-{uuid4().hex[:8]}"
    subscription = await sse_redis_bus.open_subscription(execution_id)

    ev = make_execution_requested_event(execution_id=execution_id)
    handler = disp.get_handlers(ev.event_type)[0]
    await handler(ev)

    # Await the subscription directly - true async, no polling
    msg = await asyncio.wait_for(subscription.get(RedisSSEMessage), timeout=2.0)
    assert msg is not None
    assert str(msg.event_type) == str(ev.event_type)


@pytest.mark.asyncio
async def test_router_start_and_stop(
    sse_redis_bus: SSERedisBus,
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    test_settings: Settings,
) -> None:
    test_settings.SSE_CONSUMER_POOL_SIZE = 1
    router = SSEKafkaRedisBridge(
        schema_registry=schema_registry,
        settings=test_settings,
        event_metrics=event_metrics,
        sse_bus=sse_redis_bus,
        logger=_test_logger,
    )

    async with router:
        assert router.get_stats()["num_consumers"] == 1

    assert router.get_stats()["num_consumers"] == 0
