import asyncio

import pytest
from aiokafka import AIOKafkaProducer
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent, EventMetadata, UserSettingsUpdatedEvent
from app.services.event_bus import EventBus
from app.settings import Settings
from dishka import AsyncContainer

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(scope: AsyncContainer, test_settings: Settings) -> None:
    """Test EventBus receives events from other instances (cross-instance communication)."""
    bus: EventBus = await scope.get(EventBus)

    # Future resolves when handler receives the event - no polling needed
    received_future: asyncio.Future[DomainEvent] = asyncio.get_running_loop().create_future()

    async def handler(event: DomainEvent) -> None:
        if not received_future.done():
            received_future.set_result(event)

    await bus.subscribe(f"{EventType.USER_SETTINGS_UPDATED}*", handler)

    # Simulate message from another instance by producing directly to Kafka
    event = UserSettingsUpdatedEvent(
        user_id="test-user",
        changed_fields=["theme"],
        reason="test",
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    topic = f"{test_settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.EVENT_BUS_STREAM}"
    producer = AIOKafkaProducer(bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic=topic,
            value=event.model_dump_json().encode("utf-8"),
            key=EventType.USER_SETTINGS_UPDATED.encode("utf-8"),
            headers=[("source_instance", b"other-instance")],
        )
    finally:
        await producer.stop()

    # Await the future directly - true async, no polling
    received = await asyncio.wait_for(received_future, timeout=10.0)
    assert received.event_type == EventType.USER_SETTINGS_UPDATED
    assert isinstance(received, UserSettingsUpdatedEvent)
    assert received.user_id == "test-user"
