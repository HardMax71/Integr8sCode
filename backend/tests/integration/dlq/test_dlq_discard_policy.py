import asyncio
import json
from datetime import datetime, timezone

import pytest
from confluent_kafka import Producer

from app.dlq.manager import create_dlq_manager
from app.dlq.models import DLQFields, DLQMessageStatus, RetryPolicy, RetryStrategy
import os
from app.domain.enums.kafka import KafkaTopic
from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_dlq_manager_discards_with_manual_policy(db) -> None:  # type: ignore[valid-type]
    manager = create_dlq_manager(database=db)
    prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "")
    topic = f"{prefix}{str(KafkaTopic.EXECUTION_EVENTS)}"
    manager.set_retry_policy(topic, RetryPolicy(topic=topic, strategy=RetryStrategy.MANUAL))

    ev = make_execution_requested_event(execution_id="exec-dlq-discard")

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
        coll = db.get_collection("dlq_messages")

        async def _discarded() -> None:
            doc = await coll.find_one({"event_id": ev.event_id})
            assert doc is not None
            assert doc.get(str(DLQFields.STATUS)) == DLQMessageStatus.DISCARDED

        await eventually(_discarded, timeout=10.0, interval=0.2)
