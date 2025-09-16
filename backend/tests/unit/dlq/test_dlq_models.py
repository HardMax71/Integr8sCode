from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import pytest
from confluent_kafka import KafkaError

from app.dlq import (
    AgeStatistics,
    DLQFields,
    DLQMessage,
    DLQMessageFilter,
    DLQMessageStatus,
    EventTypeStatistic,
    RetryPolicy,
    RetryStrategy,
    TopicStatistic,
    DLQStatistics,
)
from app.dlq.manager import DLQManager
from app.domain.enums.auth import LoginMethod
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.mappers.dlq_mapper import DLQMapper
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.events.schema.schema_registry import SchemaRegistryManager


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
    # Build minimal doc expected by mapper
    data = {
        DLQFields.EVENT: ev.to_dict(),
        DLQFields.ORIGINAL_TOPIC: "t",
        DLQFields.ERROR: "err",
        DLQFields.RETRY_COUNT: 2,
        DLQFields.FAILED_AT: msg.failed_at.isoformat(),
        DLQFields.STATUS: DLQMessageStatus.PENDING,
        DLQFields.PRODUCER_ID: "p1",
    }
    parsed = DLQMapper.from_mongo_document(data)
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
            return json.dumps(payload).encode()

        def headers(self):
            return [("k", b"v")]

        def offset(self): return 10

        def partition(self): return 0

    m = DLQMapper.from_kafka_message(Msg(), SchemaRegistryManager())
    assert m.original_topic == "t" and m.headers.get("k") == "v" and m.dlq_offset == 10


def test_retry_policy_should_retry_and_next_time_bounds(monkeypatch):
    msg = DLQMapper.from_failed_event(make_event(), "t", "e", "p", retry_count=0)
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
    q = DLQMapper.filter_to_query(f)
    assert q[DLQFields.STATUS] == DLQMessageStatus.PENDING and q[DLQFields.ORIGINAL_TOPIC] == "t"

    ts = TopicStatistic(topic="t", count=2, avg_retry_count=1.5)
    es = EventTypeStatistic(event_type="X", count=3)
    ages = AgeStatistics(min_age_seconds=1, max_age_seconds=10, avg_age_seconds=5)
    assert ts.topic == "t" and es.event_type == "X" and ages.min_age_seconds == 1

    stats = DLQStatistics(by_status={"pending": 1}, by_topic=[ts], by_event_type=[es], age_stats=ages)
    assert stats.by_status["pending"] == 1 and isinstance(stats.timestamp, datetime)


@pytest.mark.asyncio
async def test_dlq_manager_poll_message():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    mock_message = MagicMock()
    consumer.poll.return_value = mock_message

    result = await manager._poll_message()

    assert result == mock_message
    consumer.poll.assert_called_once_with(timeout=1.0)


@pytest.mark.asyncio
async def test_dlq_manager_validate_message_success():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    mock_message = MagicMock()
    mock_message.error.return_value = None

    result = await manager._validate_message(mock_message)

    assert result is True


@pytest.mark.asyncio
async def test_dlq_manager_validate_message_with_partition_eof():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    mock_message = MagicMock()
    mock_error = MagicMock()
    mock_error.code.return_value = KafkaError._PARTITION_EOF
    mock_message.error.return_value = mock_error

    result = await manager._validate_message(mock_message)

    assert result is False


@pytest.mark.asyncio
async def test_dlq_manager_validate_message_with_error():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    mock_message = MagicMock()
    mock_error = MagicMock()
    mock_error.code.return_value = KafkaError._ALL_BROKERS_DOWN
    mock_message.error.return_value = mock_error

    result = await manager._validate_message(mock_message)

    assert result is False


@pytest.mark.asyncio
async def test_dlq_manager_parse_message():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    ev = make_event()
    payload = {
        "event": ev.to_dict(),
        "original_topic": "test-topic",
        "error": "test error",
        "retry_count": 1,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "producer_id": "test-producer",
    }

    mock_message = MagicMock()
    mock_message.value.return_value = json.dumps(payload).encode()
    mock_message.headers.return_value = [("test-key", b"test-value")]
    mock_message.offset.return_value = 123
    mock_message.partition.return_value = 0

    with patch("app.dlq.manager.SchemaRegistryManager") as mock_schema:
        mock_schema.return_value = SchemaRegistryManager()
        result = await manager._parse_message(mock_message)

    assert isinstance(result, DLQMessage)
    assert result.original_topic == "test-topic"
    assert result.error == "test error"


@pytest.mark.asyncio
async def test_dlq_manager_extract_headers():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    mock_message = MagicMock()
    mock_message.headers.return_value = [
        ("key1", b"value1"),
        ("key2", b"value2"),
        ("key3", "value3"),
    ]

    result = manager._extract_headers(mock_message)

    assert result == {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }


@pytest.mark.asyncio
async def test_dlq_manager_extract_headers_empty():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)

    mock_message = MagicMock()
    mock_message.headers.return_value = None

    result = manager._extract_headers(mock_message)

    assert result == {}


@pytest.mark.asyncio
async def test_dlq_manager_record_message_metrics():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)
    manager.metrics = MagicMock()

    ev = make_event()
    dlq_message = DLQMessage(
        event=ev,
        original_topic="test-topic",
        error="test error",
        retry_count=1,
        failed_at=datetime.now(timezone.utc),
        status=DLQMessageStatus.PENDING,
        producer_id="test-producer",
    )

    await manager._record_message_metrics(dlq_message)

    manager.metrics.record_dlq_message_received.assert_called_once_with(
        "test-topic",
        str(ev.event_type)
    )
    manager.metrics.record_dlq_message_age.assert_called_once()


@pytest.mark.asyncio
async def test_dlq_manager_commit_and_record_duration():
    database = MagicMock()
    consumer = MagicMock()
    producer = MagicMock()

    manager = DLQManager(database, consumer, producer)
    manager.metrics = MagicMock()

    start_time = asyncio.get_event_loop().time()

    await manager._commit_and_record_duration(start_time)

    consumer.commit.assert_called_once_with(asynchronous=False)
    manager.metrics.record_dlq_processing_duration.assert_called_once()

    args = manager.metrics.record_dlq_processing_duration.call_args[0]
    assert args[1] == "process"
    assert args[0] >= 0
