from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.dlq.models import (
    AgeStatistics,
    DLQFields,
    DLQMessage,
    DLQMessageFilter,
    DLQMessageStatus,
    DLQRetryResult,
    DLQTopicSummary,
    EventTypeStatistic,
    RetryPolicy,
    RetryStrategy,
    TopicStatistic,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.domain.enums.auth import LoginMethod


def make_event():
    return UserLoggedInEvent(
        user_id="u1",
        login_method=LoginMethod.PASSWORD,
        metadata=EventMetadata(service_name="svc", service_version="1"),
    )


def test_dlqmessage_to_from_dict_roundtrip():
    ev = make_event()
    msg = DLQMessage(
        event=ev,
        original_topic="t",
        error="err",
        retry_count=2,
        failed_at=datetime.now(timezone.utc),
        status=DLQMessageStatus.PENDING,
        producer_id="p1",
    )
    doc = msg.to_dict()
    # from_dict uses SchemaRegistryManager.deserialize_json; build minimal doc expected
    data = {
        DLQFields.EVENT: ev.to_dict(),
        DLQFields.ORIGINAL_TOPIC: "t",
        DLQFields.ERROR: "err",
        DLQFields.RETRY_COUNT: 2,
        DLQFields.FAILED_AT: msg.failed_at.isoformat(),
        DLQFields.STATUS: DLQMessageStatus.PENDING,
        DLQFields.PRODUCER_ID: "p1",
    }
    parsed = DLQMessage.from_dict(data)
    assert parsed.original_topic == "t" and parsed.event_type == str(ev.event_type)


def test_from_kafka_message_and_headers():
    ev = make_event()
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
            import json
            return json.dumps(payload).encode()
        def headers(self):
            return [("k", b"v")]
        def offset(self): return 10
        def partition(self): return 0

    from app.events.schema.schema_registry import SchemaRegistryManager
    m = DLQMessage.from_kafka_message(Msg(), SchemaRegistryManager())
    assert m.original_topic == "t" and m.headers.get("k") == "v" and m.dlq_offset == 10


def test_retry_policy_should_retry_and_next_time_bounds(monkeypatch):
    msg = DLQMessage.from_failed_event(make_event(), "t", "e", "p", retry_count=0)
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


def test_filter_and_stats_models_to_dict():
    f = DLQMessageFilter(status=DLQMessageStatus.PENDING, topic="t", event_type="X")
    q = f.to_query()
    assert q[DLQFields.STATUS] == DLQMessageStatus.PENDING and q[DLQFields.ORIGINAL_TOPIC] == "t"

    ts = TopicStatistic(topic="t", count=2, avg_retry_count=1.5)
    es = EventTypeStatistic(event_type="X", count=3)
    ages = AgeStatistics(min_age_seconds=1, max_age_seconds=10, avg_age_seconds=5)
    assert ts.to_dict()["topic"] == "t" and es.to_dict()["event_type"] == "X" and ages.to_dict()["min_age"] == 1

    from app.dlq.models import DLQStatistics
    stats = DLQStatistics(by_status={"pending": 1}, by_topic=[ts], by_event_type=[es], age_stats=ages)
    d = stats.to_dict()
    assert d["by_status"]["pending"] == 1 and isinstance(d["timestamp"], datetime)

