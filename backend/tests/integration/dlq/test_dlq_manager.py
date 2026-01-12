import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
from aiokafka import AIOKafkaProducer
from app.core.database_context import Database
from app.db.docs import DLQMessageDocument
from app.dlq.manager import create_dlq_manager
from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings

from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]

_test_logger = logging.getLogger("test.dlq.manager")


@pytest.mark.asyncio
async def test_dlq_manager_persists_in_mongo(db: Database, test_settings: Settings) -> None:
    schema_registry = SchemaRegistryManager(test_settings, _test_logger)
    manager = create_dlq_manager(settings=test_settings, schema_registry=schema_registry, logger=_test_logger)

    # Use prefix from test_settings to match what the manager uses
    prefix = test_settings.KAFKA_TOPIC_PREFIX

    # Use unique execution_id to avoid conflicts with parallel test workers
    ev = make_execution_requested_event(execution_id=f"exec-dlq-persist-{uuid.uuid4().hex[:8]}")
    payload = {
        "event": ev.to_dict(),
        "original_topic": f"{prefix}{str(KafkaTopic.EXECUTION_EVENTS)}",
        "error": "handler failed",
        "retry_count": 0,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "producer_id": "tests",
    }

    # Produce to DLQ topic using aiokafka
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

    # Run the manager briefly to consume and persist
    async with manager:

        async def _exists() -> None:
            doc = await DLQMessageDocument.find_one({"event_id": ev.event_id})
            assert doc is not None

        # Poll until the document appears
        await eventually(_exists, timeout=10.0, interval=0.2)
