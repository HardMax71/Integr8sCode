from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer
from app.domain.enums.kafka import KafkaTopic
from app.services.event_bus import EventBusEvent, EventBusManager
from app.settings import Settings
from dishka import AsyncContainer
from tests.helpers.eventually import eventually

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(scope: AsyncContainer, test_settings: Settings) -> None:
    """Test EventBus receives events from other instances (cross-instance communication)."""
    manager: EventBusManager = await scope.get(EventBusManager)
    bus = await manager.get_event_bus()

    received: list[EventBusEvent] = []

    async def handler(event: EventBusEvent) -> None:
        received.append(event)

    await bus.subscribe("test.*", handler)

    # EventBus filters self-published messages (designed for cross-instance communication).
    # Simulate a message from another instance by producing directly to Kafka.
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
            headers=[("source_instance", b"other-instance")],  # Different instance
        )
    finally:
        await producer.stop()

    async def _received() -> None:
        assert any(e.event_type == "test.created" for e in received)

    await eventually(_received, timeout=5.0, interval=0.1)
