import asyncio
import json
import structlog
import uuid
from datetime import datetime, timezone

import pytest
from aiokafka import AIOKafkaConsumer
from app.core.metrics import DLQMetrics
from app.db.repositories import DLQRepository
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessage
from app.domain.enums import EventType
from app.domain.events import DLQMessageReceivedEvent, DomainEventAdapter
from app.settings import Settings
from dishka import AsyncContainer
from faststream.kafka import KafkaBroker

from tests.conftest import make_execution_requested_event

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]

_test_logger = structlog.get_logger("test.dlq.manager")


@pytest.mark.asyncio
async def test_dlq_manager_persists_and_emits_event(scope: AsyncContainer, test_settings: Settings) -> None:
    """Test that DLQ manager persists messages and emits DLQMessageReceivedEvent."""
    dlq_metrics: DLQMetrics = await scope.get(DLQMetrics)

    ev = make_execution_requested_event(execution_id=f"exec-dlq-persist-{uuid.uuid4().hex[:8]}")

    # Future resolves when DLQMessageReceivedEvent is consumed
    received_future: asyncio.Future[DLQMessageReceivedEvent] = asyncio.get_running_loop().create_future()

    # Create consumer for DLQ events topic
    dlq_events_topic = EventType.DLQ_MESSAGE_RECEIVED
    events_consumer = AIOKafkaConsumer(
        dlq_events_topic,
        bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-dlq-events.{uuid.uuid4().hex[:6]}",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    async def consume_dlq_events() -> None:
        """Consume DLQ events and set future when our event is received."""
        async for msg in events_consumer:
            try:
                payload = json.loads(msg.value.decode())
                event = DomainEventAdapter.validate_python(payload)
                if (
                    isinstance(event, DLQMessageReceivedEvent)
                    and event.dlq_event_id == ev.event_id
                    and not received_future.done()
                ):
                    received_future.set_result(event)
                    return
            except Exception as e:
                _test_logger.debug(f"Error deserializing DLQ event: {e}")

    # Create and start a broker for the manager (lifecycle managed by test)
    broker = KafkaBroker(
        test_settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    await asyncio.gather(broker.start(), events_consumer.start())
    consume_task = asyncio.create_task(consume_dlq_events())

    try:
        repository = DLQRepository(_test_logger)
        manager = DLQManager(
            settings=test_settings,
            broker=broker,
            logger=_test_logger,
            dlq_metrics=dlq_metrics,
            repository=repository,
        )

        # Build a DLQMessage directly and call handle_message (no internal consumer loop)
        dlq_msg = DLQMessage(
            event=ev,
            original_topic=EventType.EXECUTION_REQUESTED,
            error="handler failed",
            retry_count=0,
            failed_at=datetime.now(timezone.utc),
            producer_id="tests",
        )

        await manager.handle_message(dlq_msg)

        # Await the DLQMessageReceivedEvent — true async, no polling
        received = await asyncio.wait_for(received_future, timeout=5.0)
        assert received.dlq_event_id == ev.event_id
        assert received.event_type == EventType.DLQ_MESSAGE_RECEIVED
        assert received.original_event_type == EventType.EXECUTION_REQUESTED
        assert received.error == "handler failed"
    finally:
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass
        await asyncio.gather(events_consumer.stop(), broker.stop())
