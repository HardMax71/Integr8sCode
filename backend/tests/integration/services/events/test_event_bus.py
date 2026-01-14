import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer
from app.domain.enums.kafka import KafkaTopic
from app.services.event_bus import EventBusEvent, EventBusManager
from app.settings import Settings
from dishka import AsyncContainer

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(scope: AsyncContainer, test_settings: Settings) -> None:
    """Test EventBus receives events from other instances (cross-instance communication)."""
    manager: EventBusManager = await scope.get(EventBusManager)
    bus = await manager.get_event_bus()

    # Future resolves when handler receives the event - no polling needed
    received_future: asyncio.Future[EventBusEvent] = asyncio.get_running_loop().create_future()

    async def handler(event: EventBusEvent) -> None:
        if not received_future.done():
            received_future.set_result(event)

    await bus.subscribe("test.*", handler)

    # Simulate message from another instance by producing directly to Kafka
    event = EventBusEvent(
        id=str(uuid4()),
        event_type="test.created",
        timestamp=datetime.now(timezone.utc),
        payload={"x": 1},
    )

    topic = f"{test_settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.EVENT_BUS_STREAM}"
    producer = AIOKafkaProducer(bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic=topic,
            value=event.model_dump_json().encode("utf-8"),
            key=b"test.created",
            headers=[("source_instance", b"other-instance")],
        )
    finally:
        await producer.stop()

    # Await the future directly - true async, no polling
    received = await asyncio.wait_for(received_future, timeout=10.0)
    assert received.event_type == "test.created"
