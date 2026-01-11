import pytest
from app.services.event_bus import EventBusEvent, EventBusManager
from dishka import AsyncContainer
from tests.helpers.eventually import eventually

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(scope: AsyncContainer) -> None:
    manager: EventBusManager = await scope.get(EventBusManager)
    bus = await manager.get_event_bus()

    received: list[EventBusEvent] = []

    async def handler(event: EventBusEvent) -> None:
        received.append(event)

    await bus.subscribe("test.*", handler)
    await bus.publish("test.created", {"x": 1})

    async def _received() -> None:
        assert any(e.event_type == "test.created" for e in received)

    await eventually(_received, timeout=2.0, interval=0.05)
