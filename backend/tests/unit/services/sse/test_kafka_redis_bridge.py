import logging

import pytest
from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent, EventMetadata, ExecutionStartedEvent
from app.events.core import EventDispatcher
from app.services.sse.redis_bus import SSERedisBus

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.redis_bus_routing")


class _FakeBus(SSERedisBus):
    """Fake SSERedisBus for testing."""

    def __init__(self) -> None:
        # Skip parent __init__ - no real Redis
        self.published: list[tuple[str, DomainEvent]] = []
        self.logger = _test_logger

    async def publish_event(self, execution_id: str, event: DomainEvent) -> None:
        self.published.append((execution_id, event))


def _make_metadata() -> EventMetadata:
    return EventMetadata(service_name="test", service_version="1.0")


@pytest.mark.asyncio
async def test_route_domain_event_publishes_to_redis() -> None:
    fake_bus = _FakeBus()

    # Register routing handlers on a dispatcher (same pattern as the DI provider)
    disp = EventDispatcher(_test_logger)
    for et in SSERedisBus.SSE_ROUTED_EVENTS:
        disp.register_handler(et, fake_bus.route_domain_event)

    handlers = disp._handlers[EventType.EXECUTION_STARTED]
    assert len(handlers) > 0

    # Event with empty execution_id is ignored
    h = handlers[0]
    await h(ExecutionStartedEvent(execution_id="", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published == []

    # Proper event is published
    await h(ExecutionStartedEvent(execution_id="exec-123", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published and fake_bus.published[-1][0] == "exec-123"
