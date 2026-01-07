import json
import uuid
from datetime import datetime, timezone

import pytest
from app.db.docs import DLQMessageDocument
from app.domain.enums.kafka import KafkaTopic
from confluent_kafka import Producer

from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]


@pytest.mark.asyncio
async def test_dlq_manager_persists_in_mongo(db, test_settings, dlq_manager) -> None:  # type: ignore[valid-type]
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

    # Produce to DLQ topic
    producer = Producer({"bootstrap.servers": "localhost:9092"})
    producer.produce(
        topic=f"{prefix}{str(KafkaTopic.DEAD_LETTER_QUEUE)}",
        key=ev.event_id.encode(),
        value=json.dumps(payload).encode(),
    )
    producer.flush(5)

    async with dlq_manager:

        async def _exists():
            doc = await DLQMessageDocument.find_one({"event_id": ev.event_id})
            assert doc is not None

        # Poll until the document appears
        await eventually(_exists, timeout=10.0, interval=0.2)
