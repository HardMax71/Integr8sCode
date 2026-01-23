import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from app.core.metrics import DLQMetrics
from app.dlq.manager import create_dlq_manager
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DLQMessageReceivedEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]

_test_logger = logging.getLogger("test.dlq.manager")


@pytest.mark.asyncio
async def test_dlq_manager_persists_and_emits_event(scope: AsyncContainer, test_settings: Settings) -> None:
    """Test that DLQ manager persists messages and emits DLQMessageReceivedEvent."""
    schema_registry = SchemaRegistryManager(test_settings, _test_logger)
    dlq_metrics: DLQMetrics = await scope.get(DLQMetrics)
    manager = create_dlq_manager(settings=test_settings, schema_registry=schema_registry, logger=_test_logger, dlq_metrics=dlq_metrics)

    prefix = test_settings.KAFKA_TOPIC_PREFIX
    ev = make_execution_requested_event(execution_id=f"exec-dlq-persist-{uuid.uuid4().hex[:8]}")

    # Future resolves when DLQMessageReceivedEvent is consumed
    received_future: asyncio.Future[DLQMessageReceivedEvent] = asyncio.get_running_loop().create_future()

    # Create consumer for DLQ events topic
    dlq_events_topic = f"{prefix}{KafkaTopic.DLQ_EVENTS}"
    consumer = AIOKafkaConsumer(
        dlq_events_topic,
        bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-dlq-events.{uuid.uuid4().hex[:6]}",
        auto_offset_reset="earliest",
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

    payload = {
        "event": ev.model_dump(mode="json"),
        "original_topic": f"{prefix}{str(KafkaTopic.EXECUTION_EVENTS)}",
        "error": "handler failed",
        "retry_count": 0,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "producer_id": "tests",
    }

    # Produce to DLQ topic BEFORE starting consumers (auto_offset_reset="earliest")
    producer = AIOKafkaProducer(bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic=f"{prefix}{str(KafkaTopic.DEAD_LETTER_QUEUE)}",
            key=ev.event_id.encode(),
            value=json.dumps(payload).encode(),
        )
    finally:
        await producer.stop()

    # Start consumer for DLQ events
    await consumer.start()
    consume_task = asyncio.create_task(consume_dlq_events())

    try:
        # Start manager - it will consume from DLQ, persist, and emit DLQMessageReceivedEvent
        async with manager:
            # Await the DLQMessageReceivedEvent - true async, no polling
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
