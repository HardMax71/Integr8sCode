import asyncio
import json
from datetime import datetime, timezone

import pytest
from confluent_kafka import Producer

from app.dlq.manager import create_dlq_manager
import os
from app.domain.enums.kafka import KafkaTopic
from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_dlq_manager_persists_in_mongo(db) -> None:  # type: ignore[valid-type]
    manager = create_dlq_manager(database=db)

    # Build a DLQ payload matching DLQMapper.from_kafka_message expectations
    ev = make_execution_requested_event(execution_id="exec-dlq-1")

    prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "")
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

    # Run the manager briefly to consume and persist
    async with manager:
        coll = db.get_collection("dlq_messages")

        async def _exists():
            doc = await coll.find_one({"event_id": ev.event_id})
            assert doc is not None

        # Poll until the document appears
        await eventually(_exists, timeout=10.0, interval=0.2)
