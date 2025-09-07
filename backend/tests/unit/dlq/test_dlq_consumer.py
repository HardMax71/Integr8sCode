import asyncio
from types import SimpleNamespace

import pytest

from app.dlq.consumer import DLQConsumer
from app.dlq.models import DLQMessage
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.domain.enums.auth import LoginMethod
from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager


class DummyProducer:
    def __init__(self): self.calls = []
    async def produce(self, event_to_produce, headers=None, key=None):  # noqa: ANN001
        self.calls.append((event_to_produce, headers, key)); return None


def make_event():
    return UserLoggedInEvent(user_id="u1", login_method=LoginMethod.PASSWORD, metadata=EventMetadata(service_name="svc", service_version="1"))


@pytest.mark.asyncio
async def test_process_dlq_event_paths():
    prod = DummyProducer()
    c = DLQConsumer(dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE, producer=prod, schema_registry_manager=SchemaRegistryManager(), max_retry_attempts=1, retry_delay_hours=1)
    # Not ready for retry (age 0 < delay)
    await c._process_dlq_event(make_event())
    assert c.stats["processed"] == 1 and c.stats["retried"] == 0
    # Exceed max retries
    from app.dlq import models as dlqm
    called = {"n": 0}
    real_from_failed = dlqm.DLQMessage.from_failed_event
    def fake_from_failed(event, original_topic, error, producer_id, retry_count=0):  # noqa: ANN001
        # Force high retry count to hit permanent failure branch
        msg = real_from_failed(event, original_topic, error, producer_id, retry_count=5)
        called["n"] += 1
        return msg
    try:
        dlqm.DLQMessage.from_failed_event = fake_from_failed  # type: ignore[assignment]
        await c._process_dlq_event(make_event())
    finally:
        dlqm.DLQMessage.from_failed_event = real_from_failed  # type: ignore[assignment]
    assert c.stats["permanently_failed"] >= 1


@pytest.mark.asyncio
async def test_retry_messages_with_handler_and_success():
    prod = DummyProducer()
    c = DLQConsumer(dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE, producer=prod, schema_registry_manager=SchemaRegistryManager())
    # Custom handler rejects retry by inserting into internal mapping
    c._retry_handlers[str(make_event().event_type)] = lambda msg: False  # type: ignore[assignment]
    msg = DLQMessage.from_failed_event(make_event(), "t", "e", "p")
    await c._retry_messages([msg])
    assert c.stats["retried"] == 0
    # Remove handler, retry should invoke producer
    c._retry_handlers.clear()
    await c._retry_messages([msg])
    assert c.stats["retried"] == 1 and len(prod.calls) == 1


@pytest.mark.asyncio
async def test_handle_permanent_and_expired():
    prod = DummyProducer(); c = DLQConsumer(dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE, producer=prod, schema_registry_manager=SchemaRegistryManager())
    called = {"n": 0}
    async def on_fail(m): called["n"] += 1  # noqa: ANN001
    c._permanent_failure_handlers.append(on_fail)
    msg = DLQMessage.from_failed_event(make_event(), "t", "e", "p")
    await c._handle_permanent_failures([msg])
    assert c.stats["permanently_failed"] == 1 and called["n"] == 1
    await c._handle_expired_messages([msg])
    assert c.stats["expired"] == 1


@pytest.mark.asyncio
async def test_reprocess_all_stats_and_seek(monkeypatch):
    prod = DummyProducer(); c = DLQConsumer(dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE, producer=prod, schema_registry_manager=SchemaRegistryManager())
    # Install a UnifiedConsumer with a dummy underlying consumer
    class DummyKafkaConsumer:
        def assignment(self): return []
        def seek(self, *a, **k): return None
    c.consumer = SimpleNamespace(consumer=DummyKafkaConsumer())
    # Bump some stats
    c.stats["processed"] = 2; c.stats["retried"] = 1; c.stats["errors"] = 0
    res = await c.reprocess_all()
    assert res["total"] == 2 and res["retried"] == 1
