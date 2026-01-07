import json
from collections.abc import Callable
from datetime import datetime, timezone

import backoff
import pytest
from app.core.database_context import Database
from app.db.docs import DLQMessageDocument
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessageStatus, RetryPolicy, RetryStrategy
from app.domain.enums.kafka import KafkaTopic
from app.settings import Settings
from confluent_kafka import Producer

from tests.helpers import make_execution_requested_event

# xdist_group: DLQ tests share a Kafka consumer group. When running in parallel,
# different workers' managers consume each other's messages and apply wrong policies.
# Serial execution ensures each test's manager processes only its own messages.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb, pytest.mark.xdist_group("dlq")]


@pytest.mark.asyncio
async def test_dlq_manager_discards_with_manual_policy(
    db: Database,
    test_settings: Settings,
    dlq_manager: DLQManager,
    unique_id: Callable[[str], str],
) -> None:
    prefix = test_settings.KAFKA_TOPIC_PREFIX
    topic = f"{prefix}{str(KafkaTopic.EXECUTION_EVENTS)}"
    dlq_manager.set_retry_policy(topic, RetryPolicy(topic=topic, strategy=RetryStrategy.MANUAL))

    # Use unique execution_id to avoid conflicts with parallel test workers
    ev = make_execution_requested_event(execution_id=unique_id("exec-dlq-discard-"))

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

    async with dlq_manager:

        @backoff.on_exception(backoff.constant, AssertionError, max_time=10.0, interval=0.2)
        async def _wait_discarded() -> None:
            doc = await DLQMessageDocument.find_one({"event_id": ev.event_id})
            assert doc is not None
            assert doc.status == DLQMessageStatus.DISCARDED

        await _wait_discarded()
