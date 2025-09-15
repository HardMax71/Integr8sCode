import asyncio
import pytest

pytestmark = pytest.mark.unit

from app.domain.enums.events import EventType
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge


class _FakeSchema: ...


class _FakeSettings:
    KAFKA_BOOTSTRAP_SERVERS = "kafka:9092"
    SSE_CONSUMER_POOL_SIZE = 1


class _FakeEventMetrics: ...


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, object]] = []

    async def publish_event(self, execution_id: str, event: object) -> None:
        self.published.append((execution_id, event))


class _StubDispatcher:
    def __init__(self) -> None:
        self.handlers: dict[EventType, object] = {}

    def register_handler(self, et: EventType, fn: object) -> None:
        self.handlers[et] = fn


class _DummyEvent:
    def __init__(self, execution_id: str | None, et: EventType) -> None:
        self.event_type = et
        self.execution_id = execution_id

    def model_dump(self) -> dict:
        return {"execution_id": self.execution_id}


@pytest.mark.asyncio
async def test_register_and_route_events_without_kafka() -> None:
    # Build the bridge but don't call start(); directly test routing handlers
    bridge = SSEKafkaRedisBridge(
        schema_registry=_FakeSchema(),
        settings=_FakeSettings(),
        event_metrics=_FakeEventMetrics(),
        sse_bus=_FakeBus(),
    )

    disp = _StubDispatcher()
    bridge._register_routing_handlers(disp)
    assert EventType.EXECUTION_STARTED in disp.handlers

    # Event without execution_id is ignored
    h = disp.handlers[EventType.EXECUTION_STARTED]
    await h(_DummyEvent(None, EventType.EXECUTION_STARTED))
    assert bridge.sse_bus.published == []

    # Proper event is published
    await h(_DummyEvent("exec-123", EventType.EXECUTION_STARTED))
    assert bridge.sse_bus.published and bridge.sse_bus.published[-1][0] == "exec-123"

    s = bridge.get_stats()
    assert s["num_consumers"] == 0 and s["is_running"] is False
