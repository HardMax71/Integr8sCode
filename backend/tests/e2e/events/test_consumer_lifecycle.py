import logging
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from app.core.metrics import EventMetrics
from app.domain.enums.kafka import KafkaTopic
from app.events.core import EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings
from dishka import AsyncContainer

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.xdist_group("kafka_consumers")]

_test_logger = logging.getLogger("test.events.consumer_lifecycle")


@pytest.mark.asyncio
async def test_consumer_seek_operations(scope: AsyncContainer) -> None:
    """Test AIOKafkaConsumer seek operations work correctly."""
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)

    group_id = f"test-consumer-{uuid4().hex[:6]}"

    # Create AIOKafkaConsumer directly
    topic = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.EXECUTION_EVENTS}"
    kafka_consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    await kafka_consumer.start()

    try:
        # Exercise seek functions on AIOKafkaConsumer directly
        assignment = kafka_consumer.assignment()
        if assignment:
            await kafka_consumer.seek_to_beginning(*assignment)
            await kafka_consumer.seek_to_end(*assignment)
    finally:
        await kafka_consumer.stop()
