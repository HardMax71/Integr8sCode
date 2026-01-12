import logging
from unittest.mock import MagicMock

import pytest
from app.core.metrics.events import EventMetrics
from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent, EventMetadata, ExecutionStartedEvent
from app.events.core import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.kafka_redis_bridge")


class _FakeBus(SSERedisBus):
    """Fake SSERedisBus for testing."""

    def __init__(self) -> None:
        self.published: list[tuple[str, DomainEvent]] = []

    async def publish_event(self, execution_id: str, event: DomainEvent) -> None:
        self.published.append((execution_id, event))


def _make_metadata() -> EventMetadata:
    return EventMetadata(service_name="test", service_version="1.0")


@pytest.mark.asyncio
async def test_register_and_route_events_without_kafka() -> None:
    # Build the bridge but don't call start(); directly test routing handlers
    fake_bus = _FakeBus()
    mock_settings = MagicMock(spec=Settings)
    mock_settings.KAFKA_BOOTSTRAP_SERVERS = "kafka:9092"
    mock_settings.SSE_CONSUMER_POOL_SIZE = 1

    bridge = SSEKafkaRedisBridge(
        schema_registry=MagicMock(spec=SchemaRegistryManager),
        settings=mock_settings,
        event_metrics=MagicMock(spec=EventMetrics),
        sse_bus=fake_bus,
        logger=_test_logger,
    )

    disp = EventDispatcher(_test_logger)
    bridge._register_routing_handlers(disp)
    handlers = disp.get_handlers(EventType.EXECUTION_STARTED)
    assert len(handlers) > 0

    # Event with empty execution_id is ignored
    h = handlers[0]
    await h(ExecutionStartedEvent(execution_id="", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published == []

    # Proper event is published
    await h(ExecutionStartedEvent(execution_id="exec-123", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published and fake_bus.published[-1][0] == "exec-123"

    s = bridge.get_stats()
    assert s["num_consumers"] == 0 and s["is_running"] is False
