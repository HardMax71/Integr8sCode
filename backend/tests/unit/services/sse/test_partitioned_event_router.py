import asyncio
from uuid import uuid4

import pytest

from app.core.metrics.events import EventMetrics
from app.events.core import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


@pytest.mark.asyncio
async def test_router_bridges_to_redis(redis_client) -> None:  # type: ignore[valid-type]
    settings = Settings()
    router = SSEKafkaRedisBridge(
        schema_registry=SchemaRegistryManager(),
        settings=settings,
        event_metrics=EventMetrics(),
        sse_bus=SSERedisBus(redis_client),
    )
    disp = EventDispatcher()
    router._register_routing_handlers(disp)

    # Open Redis subscription for our execution id
    bus = SSERedisBus(redis_client)
    execution_id = "e1"
    subscription = await bus.open_subscription(execution_id)

    ev = ExecutionRequestedEvent(
        execution_id=execution_id,
        script="print(1)",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=30,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=5,
        metadata=EventMetadata(service_name="tests", service_version="1"),
    )
    handler = disp.get_handlers(ev.event_type)[0]
    await handler(ev)

    # Redis should receive the publication (allow short delay)
    msg = None
    for _ in range(10):
        msg = await subscription.get(timeout=0.2)
        if msg:
            break
        await asyncio.sleep(0.05)
    assert msg and msg.get("event_type") == str(ev.event_type)


@pytest.mark.asyncio
async def test_router_start_and_stop(redis_client) -> None:  # type: ignore[valid-type]
    settings = Settings()
    settings.SSE_CONSUMER_POOL_SIZE = 1
    router = SSEKafkaRedisBridge(
        schema_registry=SchemaRegistryManager(),
        settings=settings,
        event_metrics=EventMetrics(),
        sse_bus=SSERedisBus(redis_client),
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
