import asyncio
from types import SimpleNamespace

import pytest

from app.events.event_store_consumer import EventStoreConsumer
from app.domain.enums.kafka import KafkaTopic, GroupId
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


class DummyStore:
    def __init__(self):
        self.db = object()
        self.batches = []

    async def store_batch(self, events):  # noqa: ANN001
        self.batches.append(len(events))
        return {"total": len(events), "stored": len(events), "duplicates": 0, "failed": 0}


class DummySchema:
    pass


@pytest.mark.asyncio
async def test_event_store_consumer_batching(monkeypatch):
    store = DummyStore()
    c = EventStoreConsumer(
        event_store=store,
        topics=[KafkaTopic.EXECUTION_EVENTS],
        schema_registry_manager=DummySchema(),
        producer=None,
        group_id=GroupId.EVENT_STORE_CONSUMER,
        batch_size=2,
        batch_timeout_seconds=0.1,
    )
    # Patch UnifiedConsumer to avoid real Kafka
    import app.events.event_store_consumer as esc

    class UC:
        def __init__(self, *a, **k):  # noqa: ANN001
            self._cb = None

        async def start(self, topics):  # noqa: ANN001
            return None

        async def stop(self):
            return None

        def register_error_callback(self, cb):  # noqa: ANN001
            self._cb = cb

    monkeypatch.setattr(esc, "UnifiedConsumer", UC)
    # SchemaManager.apply_all no-op
    monkeypatch.setattr(esc, "SchemaManager", lambda db: SimpleNamespace(apply_all=lambda: asyncio.sleep(0)))
    # settings
    monkeypatch.setattr(esc, "get_settings", lambda: SimpleNamespace(KAFKA_BOOTSTRAP_SERVERS="kafka:29092"))

    await c.start()

    # Add two events to trigger flush by size
    e1 = PodCreatedEvent(execution_id="x1", pod_name="p1", namespace="ns", metadata=EventMetadata(service_name="s", service_version="1"))
    e2 = PodCreatedEvent(execution_id="x2", pod_name="p2", namespace="ns", metadata=EventMetadata(service_name="s", service_version="1"))
    await c._handle_event(e1)
    await c._handle_event(e2)
    # Give time for flush
    await asyncio.sleep(0.05)

    await c.stop()
    assert store.batches and store.batches[0] >= 2

