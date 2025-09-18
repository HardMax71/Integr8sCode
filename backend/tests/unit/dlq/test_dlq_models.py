from datetime import datetime, timezone
import json

import pytest

from app.dlq import (
    AgeStatistics,
    DLQFields,
    DLQMessageFilter,
    DLQMessageStatus,
    EventTypeStatistic,
    RetryPolicy,
    RetryStrategy,
    TopicStatistic,
    DLQStatistics,
)
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.infrastructure.mappers.dlq_mapper import DLQMapper


def _make_event() -> UserLoggedInEvent:
    from app.domain.enums.auth import LoginMethod
    return UserLoggedInEvent(
        user_id="u1",
        login_method=LoginMethod.PASSWORD,
        metadata=EventMetadata(service_name="svc", service_version="1"),
    )


def test_dlqmessage_mapper_roundtrip_minimal() -> None:
    ev = _make_event()
    data = {
        DLQFields.EVENT: ev.to_dict(),
        DLQFields.ORIGINAL_TOPIC: "t",
        DLQFields.ERROR: "err",
        DLQFields.RETRY_COUNT: 2,
        DLQFields.FAILED_AT: datetime.now(timezone.utc).isoformat(),
        DLQFields.STATUS: DLQMessageStatus.PENDING,
        DLQFields.PRODUCER_ID: "p1",
    }
    parsed = DLQMapper.from_mongo_document(data)
    assert parsed.original_topic == "t"
    assert parsed.event_type == str(ev.event_type)


def test_from_kafka_message_and_headers() -> None:
    ev = _make_event()
    payload = {
        "event": ev.to_dict(),
        "original_topic": "t",
        "error": "E",
        "retry_count": 1,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "producer_id": "p",
    }

    class Msg:
        def value(self):
            return json.dumps(payload).encode()

        def headers(self):
            return [("k", b"v")]

        def offset(self):
            return 10

        def partition(self):
            return 0

    m = DLQMapper.from_kafka_message(Msg(), SchemaRegistryManager())
    assert m.original_topic == "t"
    assert m.headers.get("k") == "v"
    assert m.dlq_offset == 10


def test_retry_policy_bounds() -> None:
    msg = DLQMapper.from_failed_event(_make_event(), "t", "e", "p", retry_count=0)
    # Immediate
    p1 = RetryPolicy(topic="t", strategy=RetryStrategy.IMMEDIATE)
    assert p1.should_retry(msg) is True
    assert isinstance(p1.get_next_retry_time(msg), datetime)
    # Fixed interval
    p2 = RetryPolicy(topic="t", strategy=RetryStrategy.FIXED_INTERVAL, base_delay_seconds=1)
    t2 = p2.get_next_retry_time(msg)
    assert (t2 - datetime.now(timezone.utc)).total_seconds() <= 2
    # Exponential backoff adds jitter but stays below max
    p3 = RetryPolicy(topic="t", strategy=RetryStrategy.EXPONENTIAL_BACKOFF, base_delay_seconds=1, max_delay_seconds=10)
    t3 = p3.get_next_retry_time(msg)
    assert (t3 - datetime.now(timezone.utc)).total_seconds() <= 11
    # Manual never retries
    p4 = RetryPolicy(topic="t", strategy=RetryStrategy.MANUAL)
    assert p4.should_retry(msg) is False


def test_filter_and_stats_models() -> None:
    f = DLQMessageFilter(status=DLQMessageStatus.PENDING, topic="t", event_type="X")
    q = DLQMapper.filter_to_query(f)
    assert q[DLQFields.STATUS] == DLQMessageStatus.PENDING
    assert q[DLQFields.ORIGINAL_TOPIC] == "t"

    ts = TopicStatistic(topic="t", count=2, avg_retry_count=1.5)
    es = EventTypeStatistic(event_type="X", count=3)
    ages = AgeStatistics(min_age_seconds=1, max_age_seconds=10, avg_age_seconds=5)
    stats = DLQStatistics(by_status={"pending": 1}, by_topic=[ts], by_event_type=[es], age_stats=ages)
    assert stats.by_status["pending"] == 1
    assert isinstance(stats.timestamp, datetime)

