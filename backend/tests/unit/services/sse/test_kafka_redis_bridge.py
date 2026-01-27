import logging

import pytest
from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent, EventMetadata, ExecutionStartedEvent
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.kafka_redis_bridge")


class _FakeBus(SSERedisBus):
    """Fake SSERedisBus for testing."""

    def __init__(self) -> None:
        self.published: list[tuple[str, DomainEvent]] = []

    async def publish_event(self, execution_id: str, event: DomainEvent) -> None:
        self.published.append((execution_id, event))


def _make_metadata() -> EventMetadata:
    return EventMetadata(service_name="test", service_version="1.0", user_id="test")


@pytest.mark.asyncio
async def test_handle_event_routes_to_redis_bus() -> None:
    """Test that handle_event routes events to Redis bus."""
    fake_bus = _FakeBus()

    bridge = SSEKafkaRedisBridge(
        sse_bus=fake_bus,
        logger=_test_logger,
    )

    # Event with empty execution_id is ignored
    await bridge.handle_event(
        ExecutionStartedEvent(execution_id="", pod_name="p", metadata=_make_metadata())
    )
    assert fake_bus.published == []

    # Proper event is published
    await bridge.handle_event(
        ExecutionStartedEvent(execution_id="exec-123", pod_name="p", metadata=_make_metadata())
    )
    assert fake_bus.published and fake_bus.published[-1][0] == "exec-123"


@pytest.mark.asyncio
async def test_get_status_returns_relevant_event_types() -> None:
    """Test that get_status returns relevant event types."""
    fake_bus = _FakeBus()
    bridge = SSEKafkaRedisBridge(sse_bus=fake_bus, logger=_test_logger)

    status = await bridge.get_status()
    assert "relevant_event_types" in status
    assert len(status["relevant_event_types"]) > 0


def test_get_relevant_event_types() -> None:
    """Test static method returns relevant event types."""
    event_types = SSEKafkaRedisBridge.get_relevant_event_types()
    assert EventType.EXECUTION_STARTED in event_types
    assert EventType.EXECUTION_COMPLETED in event_types
    assert EventType.RESULT_STORED in event_types
