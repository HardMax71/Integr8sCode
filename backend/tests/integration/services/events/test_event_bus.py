import asyncio
import pytest

from app.services.event_bus import EventBusManager

pytestmark = pytest.mark.integration
from tests.helpers.eventually import eventually

@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(scope) -> None:  # type: ignore[valid-type]
    manager: EventBusManager = await scope.get(EventBusManager)
    bus = await manager.get_event_bus()

    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    await bus.subscribe("test.*", handler)
    await bus.publish("test.created", {"x": 1})

    async def _received():
        assert any(e.get("event_type") == "test.created" for e in received)

    await eventually(_received, timeout=2.0, interval=0.05)
