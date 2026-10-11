from unittest.mock import AsyncMock, MagicMock

import pytest
from aiokafka.errors import KafkaError

from app.core.metrics import EventMetrics
from app.db import EventRepository
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.events import UnifiedProducer
from app.events.core.transport import KafkaEventTransport

pytestmark = pytest.mark.unit


def _event() -> UserRegisteredEvent:
    return UserRegisteredEvent(
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(service_name="test", service_version="1", user_id="u1"),
    )


def _producer() -> tuple[UnifiedProducer, AsyncMock, AsyncMock, MagicMock]:
    repo = AsyncMock(spec=EventRepository)
    transport = AsyncMock(spec=KafkaEventTransport)
    metrics = MagicMock(spec=EventMetrics)
    return UnifiedProducer(repo, transport, metrics), repo, transport, metrics


async def test_produce_stores_publishes_and_counts_every_event() -> None:
    producer, repo, transport, metrics = _producer()
    event = _event()

    await producer.produce(event_to_produce=event, key="u1")

    repo.store_event.assert_awaited_once_with(event)
    transport.publish.assert_awaited_once_with(event, event.event_type, "u1")
    metrics.record_event_published.assert_called_once_with(event.event_type)
    metrics.record_event_processing_duration.assert_called_once()


async def test_failed_publish_is_marked_and_not_counted() -> None:
    producer, repo, transport, metrics = _producer()
    transport.publish.side_effect = KafkaError("broker down")
    event = _event()

    with pytest.raises(KafkaError):
        await producer.produce(event_to_produce=event, key="u1")

    repo.mark_publish_failed.assert_awaited_once_with(event.event_id)
    metrics.record_event_published.assert_not_called()
