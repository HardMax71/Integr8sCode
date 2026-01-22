import asyncio
import logging
import uuid
from datetime import datetime, timezone

import pytest
from aiokafka import AIOKafkaConsumer
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessage
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DLQMessageReceivedEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]

_test_logger = logging.getLogger("test.dlq.manager")


@pytest.mark.asyncio
async def test_dlq_manager_persists_and_emits_event(scope: AsyncContainer, test_settings: Settings) -> None:
    """Test that DLQ manager persists messages and emits DLQMessageReceivedEvent.

    Note: DLQManager is now a simple service (not a DI-started consumer).
    Message consumption is handled by the FastStream worker (workers/dlq_processor.py).
    This test exercises DLQManager.process_message() directly.
    """
    schema_registry = await scope.get(SchemaRegistryManager)
    dlq_manager = await scope.get(DLQManager)

    prefix = test_settings.KAFKA_TOPIC_PREFIX
    ev = make_execution_requested_event(execution_id=f"exec-dlq-persist-{uuid.uuid4().hex[:8]}")

    # Create a typed DLQMessage (as FastStream would deserialize it)
    dlq_message = DLQMessage(
        event=ev,
        original_topic=f"{prefix}{KafkaTopic.EXECUTION_EVENTS}",
        error="handler failed",
        retry_count=0,
        failed_at=datetime.now(timezone.utc),
        producer_id="tests",
    )

    # Future resolves when DLQMessageReceivedEvent is consumed
    received_future: asyncio.Future[DLQMessageReceivedEvent] = asyncio.get_running_loop().create_future()

    # Create consumer for DLQ events topic
    dlq_events_topic = f"{prefix}{KafkaTopic.DLQ_EVENTS}"
    consumer = AIOKafkaConsumer(
        dlq_events_topic,
        bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-dlq-events.{uuid.uuid4().hex[:6]}",
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )

    async def consume_dlq_events() -> None:
        """Consume DLQ events and set future when our event is received."""
        async for msg in consumer:
            try:
                event = await schema_registry.deserialize_event(msg.value, dlq_events_topic)
                if (
                    isinstance(event, DLQMessageReceivedEvent)
                    and event.dlq_event_id == ev.event_id
                    and not received_future.done()
                ):
                    received_future.set_result(event)
                    return
            except Exception as e:
                _test_logger.debug(f"Error deserializing DLQ event: {e}")

    # Start consumer BEFORE processing (auto_offset_reset="latest")
    await consumer.start()
    # Small delay to ensure consumer is fully subscribed and ready
    await asyncio.sleep(0.5)
    consume_task = asyncio.create_task(consume_dlq_events())

    try:
        # Process message directly via DLQManager (simulating FastStream handler)
        await dlq_manager.process_message(dlq_message)

        # Wait for the emitted event
        received = await asyncio.wait_for(received_future, timeout=15.0)
        assert received.dlq_event_id == ev.event_id
        assert received.event_type == EventType.DLQ_MESSAGE_RECEIVED
        assert received.original_event_type == str(EventType.EXECUTION_REQUESTED)
        assert received.error == "handler failed"
    finally:
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass
        await consumer.stop()
