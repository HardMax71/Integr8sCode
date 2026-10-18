import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import structlog
from faststream.kafka import KafkaBroker
from opentelemetry import trace

from app.db.docs import DLQMessageDocument
from app.db.repositories import DLQRepository
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessage, DLQMessageStatus
from app.domain.enums import EventType
from app.domain.events import DLQMessageReceivedEvent, ExecutionRequestedEvent
from app.settings import Settings
from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e]


@pytest.fixture
async def failed_event() -> AsyncIterator[ExecutionRequestedEvent]:
    """The event the test dead-letters; its row goes when the test ends, so the worker's retry job never sees it."""
    event = make_execution_requested_event(execution_id=f"exec-dlq-{uuid.uuid4().hex[:8]}")
    yield event
    await DLQMessageDocument.find({"event.event_id": event.event_id}).delete()


async def test_dlq_manager_stores_the_message_and_announces_it(
    test_settings: Settings,
    dlq_repository: DLQRepository,
    failed_event: ExecutionRequestedEvent,
) -> None:
    broker = AsyncMock(spec=KafkaBroker)
    manager = DLQManager(
        settings=test_settings,
        broker=broker,
        logger=structlog.get_logger("test.dlq.manager"),
        tracer=trace.NoOpTracer(),
        repository=dlq_repository,
    )

    await manager.handle_message(
        DLQMessage(
            event=failed_event,
            original_topic=EventType.EXECUTION_REQUESTED,
            consumer_group=f"test-group-{uuid.uuid4().hex[:8]}",
            error="handler failed",
            retry_count=0,
            failed_at=datetime.now(timezone.utc),
            producer_id="tests",
        )
    )

    stored = await DLQMessageDocument.find_one({"event.event_id": failed_event.event_id})
    assert stored is not None
    assert stored.status == DLQMessageStatus.SCHEDULED
    broker.publish.assert_awaited_once()
    announced = broker.publish.call_args.args[0]
    assert isinstance(announced, DLQMessageReceivedEvent)
    assert (announced.dlq_event_id, announced.original_event_type, announced.error) == (
        failed_event.event_id,
        EventType.EXECUTION_REQUESTED,
        "handler failed",
    )
    assert broker.publish.call_args.kwargs == {"topic": EventType.DLQ_MESSAGE_RECEIVED}
