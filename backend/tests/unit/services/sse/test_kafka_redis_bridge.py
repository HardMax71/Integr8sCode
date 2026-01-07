import logging

import pytest
from app.domain.enums.events import EventType
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.kafka_redis_bridge")


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

    def model_dump(self) -> dict[str, str | None]:
        return {"execution_id": self.execution_id}


@pytest.mark.asyncio
async def test_register_and_route_events_without_kafka() -> None:
    # Build the bridge but don't call start(); directly test routing handlers
    bridge = SSEKafkaRedisBridge(
        schema_registry=_FakeSchema(),  # type: ignore[arg-type]
        settings=_FakeSettings(),  # type: ignore[arg-type]
        event_metrics=_FakeEventMetrics(),  # type: ignore[arg-type]
        sse_bus=_FakeBus(),  # type: ignore[arg-type]
        logger=_test_logger,
    )

    disp = _StubDispatcher()
    bridge._register_routing_handlers(disp)  # type: ignore[arg-type]
    assert EventType.EXECUTION_STARTED in disp.handlers

    # Event without execution_id is ignored
    h = disp.handlers[EventType.EXECUTION_STARTED]
    await h(_DummyEvent(None, EventType.EXECUTION_STARTED))  # type: ignore[operator]
    fake_bus: _FakeBus = bridge.sse_bus  # type: ignore[assignment]
    assert fake_bus.published == []

    # Proper event is published
    await h(_DummyEvent("exec-123", EventType.EXECUTION_STARTED))  # type: ignore[operator]
    assert fake_bus.published and fake_bus.published[-1][0] == "exec-123"

    s = bridge.get_stats()
    assert s["num_consumers"] == 0 and s["is_running"] is False
