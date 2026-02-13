import structlog

import pytest
from app.domain.events import DomainEvent, EventMetadata, ExecutionStartedEvent
from app.services.sse import SSERedisBus

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.sse.redis_bus_routing")


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

    # Event with empty execution_id is ignored
    await fake_bus.route_domain_event(ExecutionStartedEvent(execution_id="", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published == []

    # Proper event is published
    await fake_bus.route_domain_event(ExecutionStartedEvent(execution_id="exec-123", pod_name="p", metadata=_make_metadata()))
    assert fake_bus.published and fake_bus.published[-1][0] == "exec-123"
