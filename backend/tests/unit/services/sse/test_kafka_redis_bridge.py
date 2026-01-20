import logging

import pytest
from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent, EventMetadata, ExecutionStartedEvent
from app.events.core import EventDispatcher
from app.services.sse.event_router import SSEEventRouter
from app.services.sse.redis_bus import SSERedisBus

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.event_router")


class _FakeBus(SSERedisBus):
    """Fake SSERedisBus for testing."""

    def __init__(self) -> None:
        self.published: list[tuple[str, DomainEvent]] = []

    async def publish_event(self, execution_id: str, event: DomainEvent) -> None:
        self.published.append((execution_id, event))


def _make_metadata() -> EventMetadata:
    return EventMetadata(service_name="test", service_version="1.0")


@pytest.mark.asyncio
async def test_event_router_registers_and_routes_events() -> None:
    """Test that SSEEventRouter registers handlers and routes events to Redis."""
    fake_bus = _FakeBus()
    router = SSEEventRouter(sse_bus=fake_bus, logger=_test_logger)

    # Register handlers with dispatcher
    disp = EventDispatcher(_test_logger)
    router.register_handlers(disp)

    # Verify handler was registered
    handlers = disp.get_handlers(EventType.EXECUTION_STARTED)
    assert len(handlers) > 0

    # Event with empty execution_id is ignored
    h = handlers[0]
    await h(ExecutionStartedEvent(execution_id="", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published == []

    # Proper event is published
    await h(ExecutionStartedEvent(execution_id="exec-123", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published and fake_bus.published[-1][0] == "exec-123"
