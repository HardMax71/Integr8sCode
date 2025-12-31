import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import pytest
from confluent_kafka import Producer

from app.db.docs import DLQMessageDocument
from app.dlq.manager import create_dlq_manager
from app.dlq.models import DLQMessageStatus, RetryPolicy, RetryStrategy
from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import create_schema_registry_manager
from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]

_test_logger = logging.getLogger("test.dlq.discard_policy")


@pytest.mark.asyncio
async def test_dlq_manager_discards_with_manual_policy(db) -> None:  # type: ignore[valid-type]
    schema_registry = create_schema_registry_manager(_test_logger)
    manager = create_dlq_manager(schema_registry=schema_registry, logger=_test_logger)
    prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "")
    topic = f"{prefix}{str(KafkaTopic.EXECUTION_EVENTS)}"
    manager.set_retry_policy(topic, RetryPolicy(topic=topic, strategy=RetryStrategy.MANUAL))

    # Use unique execution_id to avoid conflicts with parallel test workers
    ev = make_execution_requested_event(execution_id=f"exec-dlq-discard-{uuid.uuid4().hex[:8]}")

    payload = {
        "event": ev.to_dict(),
        "original_topic": topic,
        "error": "boom",
        "retry_count": 0,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "producer_id": "tests",
    }

    producer = Producer({"bootstrap.servers": "localhost:9092"})
    producer.produce(
        topic=f"{prefix}{str(KafkaTopic.DEAD_LETTER_QUEUE)}",
        key=ev.event_id.encode(),
        value=json.dumps(payload).encode(),
    )
    producer.flush(5)

    async with manager:
        async def _discarded() -> None:
            doc = await DLQMessageDocument.find_one({"event_id": ev.event_id})
            assert doc is not None
            assert doc.status == DLQMessageStatus.DISCARDED

        await eventually(_discarded, timeout=10.0, interval=0.2)
