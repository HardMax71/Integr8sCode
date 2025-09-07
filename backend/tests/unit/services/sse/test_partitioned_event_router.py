import pytest

from app.domain.enums.events import EventType
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.sse.partitioned_event_router import PartitionedSSERouter
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


class StubEventMetrics:
    def record_event_buffer_processed(self) -> None:
        pass

    def record_event_buffer_dropped(self) -> None:
        pass


class StubConnectionMetrics:
    def increment_sse_connections(self, _: str) -> None:
        pass

    def decrement_sse_connections(self, _: str) -> None:
        pass


class DummySchemaRegistry(SchemaRegistryManager):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        pass


class DummyBus(SSERedisBus):
    def __init__(self):
        # type: ignore[call-arg]
        pass
    async def publish_event(self, execution_id, event):  # noqa: ANN001
        return None


def test_priority_mapping() -> None:
    router = PartitionedSSERouter(
        schema_registry=DummySchemaRegistry(),
        settings=Settings(),
        event_metrics=StubEventMetrics(),
        connection_metrics=StubConnectionMetrics(),
        sse_bus=DummyBus(),
    )

    assert router._get_event_priority(EventType.RESULT_STORED).name == "CRITICAL"  # type: ignore[attr-defined]
    assert router._get_event_priority(EventType.EXECUTION_COMPLETED).name == "HIGH"
    # Pod events routed as LOW
    assert router._get_event_priority(EventType.POD_CREATED).name == "LOW"
    # Default path
    assert router._get_event_priority(EventType.EXECUTION_REQUESTED).name == "NORMAL"


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_buffers() -> None:
    router = PartitionedSSERouter(
        schema_registry=DummySchemaRegistry(),
        settings=Settings(),
        event_metrics=StubEventMetrics(),
        connection_metrics=StubConnectionMetrics(),
        sse_bus=DummyBus(),
    )

    buf = await router.subscribe("exec-1")
    assert buf is not None
    stats = router.get_stats()
    assert stats["active_executions"] == 1
    assert stats["total_buffers"] == 1

    await router.unsubscribe("exec-1")
    stats2 = router.get_stats()
    assert stats2["active_executions"] == 0
    assert stats2["total_buffers"] == 0

import asyncio

from app.domain.enums.events import EventType
from app.services.sse.partitioned_event_router import PartitionedSSERouter
from app.events.core.dispatcher import EventDispatcher


class DummySchema: pass
class DummySettings:
    SSE_CONSUMER_POOL_SIZE = 0
    KAFKA_BOOTSTRAP_SERVERS = "kafka:29092"


class EM:
    def __init__(self): self.dropped = self.processed = 0
    def record_event_buffer_processed(self): self.processed += 1
    def record_event_buffer_dropped(self): self.dropped += 1


class CM:
    def increment_sse_connections(self, x): pass  # noqa: ANN001
    def decrement_sse_connections(self, x): pass  # noqa: ANN001


class StubBuffer:
    def __init__(self, ok=True): self.ok = ok
    async def put(self, *a, **k): return self.ok  # noqa: ANN001


def test_route_event_missing_execution_id_skips():
    router = PartitionedSSERouter(DummySchema(), DummySettings(0), EM(), CM(), DummyBus())
    disp = EventDispatcher()
    router._register_routing_handlers(disp)
    h = disp.get_handlers(EventType.POD_CREATED)[0]
    class E:
        event_type = EventType.POD_CREATED
        def model_dump(self): return {}
    # Should not crash and not process
    asyncio.get_event_loop().run_until_complete(h(E()))


def test_route_event_no_active_subscription_skips():
    em = EM()
    router = PartitionedSSERouter(DummySchema(), DummySettings(0), em, CM(), DummyBus())
    disp = EventDispatcher()
    router._register_routing_handlers(disp)
    h = disp.get_handlers(EventType.POD_CREATED)[0]
    class E:
        event_type = EventType.POD_CREATED
        def model_dump(self): return {"execution_id": "e-x"}
    asyncio.get_event_loop().run_until_complete(h(E()))
    assert em.processed == 0 and em.dropped == 0


def test_route_event_drop_when_put_false():
    em = EM()
    router = PartitionedSSERouter(DummySchema(), DummySettings(0), em, CM(), DummyBus())
    disp = EventDispatcher()
    router._register_routing_handlers(disp)
    # Install a stub buffer that fails put
    router.execution_buffers["e1"] = StubBuffer(ok=False)
    h = disp.get_handlers(EventType.POD_CREATED)[0]
    class E:
        event_type = EventType.POD_CREATED
        def model_dump(self): return {"execution_id": "e1"}
    asyncio.get_event_loop().run_until_complete(h(E()))
    assert em.dropped == 1

import asyncio

import pytest

from app.events.core.dispatcher import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.sse.partitioned_event_router import PartitionedSSERouter
from app.settings import Settings


class DummySchema(SchemaRegistryManager):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        pass


class StubEventMetrics:
    def record_event_buffer_processed(self) -> None: pass
    def record_event_buffer_dropped(self) -> None: pass


class StubConnectionMetrics:
    def increment_sse_connections(self, x): pass  # noqa: ANN001
    def decrement_sse_connections(self, x): pass  # noqa: ANN001


@pytest.mark.asyncio
async def test_router_registers_and_routes_event():
    router = PartitionedSSERouter(DummySchema(), Settings(), StubEventMetrics(), StubConnectionMetrics(), DummyBus())
    disp = EventDispatcher()
    router._register_routing_handlers(disp)
    buf = await router.subscribe("e1")
    # Create an event and dispatch via registered handler
    ev = ExecutionRequestedEvent(
        execution_id="e1",
        script="print(1)",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=30,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=5,
        metadata=EventMetadata(service_name="s", service_version="1"),
    )
    handler = disp.get_handlers(ev.event_type)[0]
    await handler(ev)
    out = await buf.get(timeout=0.1)
    assert out is not None
    await router.unsubscribe("e1")

import pytest

from app.services.sse.partitioned_event_router import PartitionedSSERouter


class DummySchema:
    pass


class StubEventMetrics:
    def record_event_buffer_processed(self): pass
    def record_event_buffer_dropped(self): pass


class StubConnectionMetrics:
    def increment_sse_connections(self, x): pass  # noqa: ANN001
    def decrement_sse_connections(self, x): pass  # noqa: ANN001


class DummyConsumer:
    async def start(self, topics):  # noqa: ANN001
        self.topics = topics
    async def stop(self):
        self.stopped = True


class DummySettings:
    SSE_CONSUMER_POOL_SIZE = 1
    KAFKA_BOOTSTRAP_SERVERS = "kafka:29092"


@pytest.mark.asyncio
async def test_router_start_and_stop(monkeypatch):
    router = PartitionedSSERouter(DummySchema(), DummySettings(1), StubEventMetrics(), StubConnectionMetrics(), DummyBus())
    # Patch _create_consumer to return our dummy
    async def fake_create_consumer(i):  # noqa: ANN001
        return DummyConsumer()
    monkeypatch.setattr(router, "_create_consumer", fake_create_consumer)

    await router.start()
    stats = router.get_stats()
    assert stats["num_consumers"] == 1
    await router.stop()
    assert router.get_stats()["num_consumers"] == 0
    # idempotent start/stop
    await router.start()
    await router.start()  # second call no-op
    await router.stop()
    await router.stop()  # second call no-op
import asyncio

import pytest

from app.services.sse.partitioned_event_router import PartitionedSSERouter


class DummySchema: pass


class DummySettings:
    def __init__(self, n):  # noqa: ANN001
        self.SSE_CONSUMER_POOL_SIZE = n
        self.KAFKA_BOOTSTRAP_SERVERS = "kafka:29092"


class DummyEM:
    def record_event_buffer_processed(self): pass  # noqa: ANN001
    def record_event_buffer_dropped(self): pass  # noqa: ANN001


class DummyCM:
    def __init__(self): self.count = 0
    def increment_sse_connections(self, _): self.count += 1  # noqa: ANN001
    def decrement_sse_connections(self, _): self.count -= 1  # noqa: ANN001


class DummyConsumer:
    def __init__(self): self.stopped = False
    async def stop(self): self.stopped = True  # noqa: ANN001


@pytest.mark.asyncio
async def test_start_stop_and_subscribe_unsubscribe(monkeypatch):
    # Use pool size 3 to cover >1 consumers
    settings = DummySettings(3)
    cm = DummyCM()
    router = PartitionedSSERouter(DummySchema(), settings, DummyEM(), cm, DummyBus())

    async def fake_create_consumer(i):  # noqa: ANN001
        return DummyConsumer()

    monkeypatch.setattr(router, "_create_consumer", fake_create_consumer)

    await router.start()
    assert router.get_stats()["num_consumers"] == 3

    # Subscribe creates buffer and increments connection count
    buf = await router.subscribe("exec-1")
    assert "exec-1" in router.execution_buffers
    assert cm.count == 1
    # Unsubscribe cleans up and decrements
    await router.unsubscribe("exec-1")
    assert "exec-1" not in router.execution_buffers
    assert cm.count == 0

    # Stop should stop consumers and clear buffers
    await router.stop()
    stats = router.get_stats()
    assert stats["is_running"] is False
    assert stats["num_consumers"] == 0
