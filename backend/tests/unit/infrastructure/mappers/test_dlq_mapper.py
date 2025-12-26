"""Tests for DLQ mapper."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from app.dlq.models import (
    DLQBatchRetryResult,
    DLQFields,
    DLQMessage,
    DLQMessageFilter,
    DLQMessageStatus,
    DLQMessageUpdate,
    DLQRetryResult,
)
from app.domain.enums.events import EventType
from app.infrastructure.mappers.dlq_mapper import DLQMapper
from confluent_kafka import Message

from tests.helpers import make_execution_requested_event


@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    return make_execution_requested_event(
        execution_id="exec-123",
        script="print('test')",
    )


@pytest.fixture
def sample_dlq_message(sample_event):
    """Create a sample DLQ message."""
    return DLQMessage(
        event=sample_event,
        original_topic="execution-events",
        error="Test error",
        retry_count=2,
        failed_at=datetime.now(timezone.utc),
        status=DLQMessageStatus.PENDING,
        producer_id="test-producer",
        event_id="event-123",
        created_at=datetime.now(timezone.utc),
        last_updated=datetime.now(timezone.utc),
        next_retry_at=datetime.now(timezone.utc),
        retried_at=datetime.now(timezone.utc),
        discarded_at=datetime.now(timezone.utc),
        discard_reason="Max retries exceeded",
        dlq_offset=100,
        dlq_partition=1,
        last_error="Connection timeout",
    )


class TestDLQMapper:
    """Test DLQ mapper."""

    def test_to_mongo_document_full(self, sample_dlq_message):
        """Test converting DLQ message to MongoDB document with all fields."""
        doc = DLQMapper.to_mongo_document(sample_dlq_message)

        assert doc[DLQFields.EVENT] == sample_dlq_message.event.to_dict()
        assert doc[DLQFields.ORIGINAL_TOPIC] == "execution-events"
        assert doc[DLQFields.ERROR] == "Test error"
        assert doc[DLQFields.RETRY_COUNT] == 2
        assert doc[DLQFields.STATUS] == DLQMessageStatus.PENDING
        assert doc[DLQFields.PRODUCER_ID] == "test-producer"
        assert doc[DLQFields.EVENT_ID] == "event-123"
        assert DLQFields.CREATED_AT in doc
        assert DLQFields.LAST_UPDATED in doc
        assert DLQFields.NEXT_RETRY_AT in doc
        assert DLQFields.RETRIED_AT in doc
        assert DLQFields.DISCARDED_AT in doc
        assert doc[DLQFields.DISCARD_REASON] == "Max retries exceeded"
        assert doc[DLQFields.DLQ_OFFSET] == 100
        assert doc[DLQFields.DLQ_PARTITION] == 1
        assert doc[DLQFields.LAST_ERROR] == "Connection timeout"

    def test_to_mongo_document_minimal(self, sample_event):
        """Test converting minimal DLQ message to MongoDB document."""
        msg = DLQMessage(
            event=sample_event,
            original_topic="test-topic",
            error="Error",
            retry_count=0,
            failed_at=datetime.now(timezone.utc),
            status=DLQMessageStatus.PENDING,
            producer_id="producer",
        )

        doc = DLQMapper.to_mongo_document(msg)

        assert doc[DLQFields.EVENT] == sample_event.to_dict()
        assert doc[DLQFields.ORIGINAL_TOPIC] == "test-topic"
        assert doc[DLQFields.ERROR] == "Error"
        assert doc[DLQFields.RETRY_COUNT] == 0
        # event_id is extracted from event in __post_init__ if not provided
        assert doc[DLQFields.EVENT_ID] == sample_event.event_id
        # created_at is set in __post_init__ if not provided
        assert DLQFields.CREATED_AT in doc
        assert DLQFields.LAST_UPDATED not in doc
        assert DLQFields.NEXT_RETRY_AT not in doc
        assert DLQFields.RETRIED_AT not in doc
        assert DLQFields.DISCARDED_AT not in doc
        assert DLQFields.DISCARD_REASON not in doc
        assert DLQFields.DLQ_OFFSET not in doc
        assert DLQFields.DLQ_PARTITION not in doc
        assert DLQFields.LAST_ERROR not in doc

    def test_from_mongo_document_full(self, sample_dlq_message):
        """Test creating DLQ message from MongoDB document with all fields."""
        doc = DLQMapper.to_mongo_document(sample_dlq_message)

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager") as mock_registry:
            mock_registry.return_value.deserialize_json.return_value = sample_dlq_message.event

            msg = DLQMapper.from_mongo_document(doc)

            assert msg.event == sample_dlq_message.event
            assert msg.original_topic == "execution-events"
            assert msg.error == "Test error"
            assert msg.retry_count == 2
            assert msg.status == DLQMessageStatus.PENDING
            assert msg.producer_id == "test-producer"
            assert msg.event_id == "event-123"
            assert msg.discard_reason == "Max retries exceeded"
            assert msg.dlq_offset == 100
            assert msg.dlq_partition == 1
            assert msg.last_error == "Connection timeout"

    def test_from_mongo_document_minimal(self, sample_event):
        """Test creating DLQ message from minimal MongoDB document."""
        doc = {
            DLQFields.EVENT: sample_event.to_dict(),
            DLQFields.FAILED_AT: datetime.now(timezone.utc),
        }

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager") as mock_registry:
            mock_registry.return_value.deserialize_json.return_value = sample_event

            msg = DLQMapper.from_mongo_document(doc)

            assert msg.event == sample_event
            assert msg.original_topic == ""
            assert msg.error == ""
            assert msg.retry_count == 0
            assert msg.status == DLQMessageStatus.PENDING
            assert msg.producer_id == "unknown"

    def test_from_mongo_document_with_string_datetime(self, sample_event):
        """Test creating DLQ message from document with string datetime."""
        now = datetime.now(timezone.utc)
        doc = {
            DLQFields.EVENT: sample_event.to_dict(),
            DLQFields.FAILED_AT: now.isoformat(),
            DLQFields.CREATED_AT: now.isoformat(),
        }

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager") as mock_registry:
            mock_registry.return_value.deserialize_json.return_value = sample_event

            msg = DLQMapper.from_mongo_document(doc)

            assert msg.failed_at.replace(microsecond=0) == now.replace(microsecond=0)
            assert msg.created_at.replace(microsecond=0) == now.replace(microsecond=0)

    def test_from_mongo_document_missing_failed_at(self, sample_event):
        """Test creating DLQ message from document without failed_at raises error."""
        doc = {
            DLQFields.EVENT: sample_event.to_dict(),
        }

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager") as mock_registry:
            mock_registry.return_value.deserialize_json.return_value = sample_event

            with pytest.raises(ValueError, match="Missing failed_at"):
                DLQMapper.from_mongo_document(doc)

    def test_from_mongo_document_invalid_failed_at(self, sample_event):
        """Test creating DLQ message with invalid failed_at raises error."""
        doc = {
            DLQFields.EVENT: sample_event.to_dict(),
            DLQFields.FAILED_AT: None,
        }

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager") as mock_registry:
            mock_registry.return_value.deserialize_json.return_value = sample_event

            with pytest.raises(ValueError, match="Missing failed_at"):
                DLQMapper.from_mongo_document(doc)

    def test_from_mongo_document_invalid_event(self):
        """Test creating DLQ message with invalid event raises error."""
        doc = {
            DLQFields.FAILED_AT: datetime.now(timezone.utc),
            DLQFields.EVENT: "not a dict",
        }

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager"):
            with pytest.raises(ValueError, match="Missing or invalid event data"):
                DLQMapper.from_mongo_document(doc)

    def test_from_mongo_document_invalid_datetime_type(self, sample_event):
        """Test creating DLQ message with invalid datetime type raises error."""
        doc = {
            DLQFields.EVENT: sample_event.to_dict(),
            DLQFields.FAILED_AT: 12345,  # Invalid type
        }

        with patch("app.infrastructure.mappers.dlq_mapper.SchemaRegistryManager") as mock_registry:
            mock_registry.return_value.deserialize_json.return_value = sample_event

            with pytest.raises(ValueError, match="Invalid datetime type"):
                DLQMapper.from_mongo_document(doc)

    def test_from_kafka_message(self, sample_event):
        """Test creating DLQ message from Kafka message."""
        mock_msg = MagicMock(spec=Message)

        event_data = {
            "event": sample_event.to_dict(),
            "original_topic": "test-topic",
            "error": "Test error",
            "retry_count": 3,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "producer_id": "test-producer",
        }
        mock_msg.value.return_value = json.dumps(event_data).encode("utf-8")
        mock_msg.headers.return_value = [
            ("trace-id", b"123"),
            ("correlation-id", b"456"),
        ]
        mock_msg.offset.return_value = 200
        mock_msg.partition.return_value = 2

        mock_registry = MagicMock()
        mock_registry.deserialize_json.return_value = sample_event

        msg = DLQMapper.from_kafka_message(mock_msg, mock_registry)

        assert msg.event == sample_event
        assert msg.original_topic == "test-topic"
        assert msg.error == "Test error"
        assert msg.retry_count == 3
        assert msg.producer_id == "test-producer"
        assert msg.dlq_offset == 200
        assert msg.dlq_partition == 2
        assert msg.headers["trace-id"] == "123"
        assert msg.headers["correlation-id"] == "456"

    def test_from_kafka_message_no_value(self):
        """Test creating DLQ message from Kafka message without value raises error."""
        mock_msg = MagicMock(spec=Message)
        mock_msg.value.return_value = None

        mock_registry = MagicMock()

        with pytest.raises(ValueError, match="Message has no value"):
            DLQMapper.from_kafka_message(mock_msg, mock_registry)

    def test_from_kafka_message_minimal(self, sample_event):
        """Test creating DLQ message from minimal Kafka message."""
        mock_msg = MagicMock(spec=Message)

        event_data = {
            "event": sample_event.to_dict(),
        }
        mock_msg.value.return_value = json.dumps(event_data).encode("utf-8")
        mock_msg.headers.return_value = None
        mock_msg.offset.return_value = -1  # Invalid offset
        mock_msg.partition.return_value = -1  # Invalid partition

        mock_registry = MagicMock()
        mock_registry.deserialize_json.return_value = sample_event

        msg = DLQMapper.from_kafka_message(mock_msg, mock_registry)

        assert msg.event == sample_event
        assert msg.original_topic == "unknown"
        assert msg.error == "Unknown error"
        assert msg.retry_count == 0
        assert msg.producer_id == "unknown"
        assert msg.dlq_offset is None
        assert msg.dlq_partition is None
        assert msg.headers == {}

    def test_to_response_dict(self, sample_dlq_message):
        """Test converting DLQ message to response dictionary."""
        result = DLQMapper.to_response_dict(sample_dlq_message)

        assert result["event_id"] == "event-123"
        assert result["event_type"] == sample_dlq_message.event_type
        assert result["event"] == sample_dlq_message.event.to_dict()
        assert result["original_topic"] == "execution-events"
        assert result["error"] == "Test error"
        assert result["retry_count"] == 2
        assert result["status"] == DLQMessageStatus.PENDING
        assert result["producer_id"] == "test-producer"
        assert result["dlq_offset"] == 100
        assert result["dlq_partition"] == 1
        assert result["last_error"] == "Connection timeout"
        assert result["discard_reason"] == "Max retries exceeded"
        assert "age_seconds" in result
        assert "failed_at" in result
        assert "next_retry_at" in result
        assert "retried_at" in result
        assert "discarded_at" in result

    def test_retry_result_to_dict_success(self):
        """Test converting successful retry result to dictionary."""
        result = DLQRetryResult(event_id="event-123", status="success")

        d = DLQMapper.retry_result_to_dict(result)

        assert d == {"event_id": "event-123", "status": "success"}

    def test_retry_result_to_dict_with_error(self):
        """Test converting retry result with error to dictionary."""
        result = DLQRetryResult(event_id="event-123", status="failed", error="Connection error")

        d = DLQMapper.retry_result_to_dict(result)

        assert d == {"event_id": "event-123", "status": "failed", "error": "Connection error"}

    def test_batch_retry_result_to_dict(self):
        """Test converting batch retry result to dictionary."""
        details = [
            DLQRetryResult(event_id="event-1", status="success"),
            DLQRetryResult(event_id="event-2", status="failed", error="Error"),
        ]
        result = DLQBatchRetryResult(total=2, successful=1, failed=1, details=details)

        d = DLQMapper.batch_retry_result_to_dict(result)

        assert d["total"] == 2
        assert d["successful"] == 1
        assert d["failed"] == 1
        assert len(d["details"]) == 2
        assert d["details"][0] == {"event_id": "event-1", "status": "success"}
        assert d["details"][1] == {"event_id": "event-2", "status": "failed", "error": "Error"}

    def test_from_failed_event(self, sample_event):
        """Test creating DLQ message from failed event."""
        msg = DLQMapper.from_failed_event(
            event=sample_event,
            original_topic="test-topic",
            error="Processing failed",
            producer_id="producer-123",
            retry_count=5,
        )

        assert msg.event == sample_event
        assert msg.original_topic == "test-topic"
        assert msg.error == "Processing failed"
        assert msg.producer_id == "producer-123"
        assert msg.retry_count == 5
        assert msg.status == DLQMessageStatus.PENDING
        assert msg.failed_at is not None

    def test_update_to_mongo_full(self):
        """Test converting DLQ message update to MongoDB update document."""
        update = DLQMessageUpdate(
            status=DLQMessageStatus.RETRIED,
            retry_count=3,
            next_retry_at=datetime.now(timezone.utc),
            retried_at=datetime.now(timezone.utc),
            discarded_at=datetime.now(timezone.utc),
            discard_reason="Too many retries",
            last_error="Connection timeout",
            extra={"custom_field": "value"},
        )

        doc = DLQMapper.update_to_mongo(update)

        assert doc[str(DLQFields.STATUS)] == DLQMessageStatus.RETRIED
        assert doc[str(DLQFields.RETRY_COUNT)] == 3
        assert str(DLQFields.NEXT_RETRY_AT) in doc
        assert str(DLQFields.RETRIED_AT) in doc
        assert str(DLQFields.DISCARDED_AT) in doc
        assert doc[str(DLQFields.DISCARD_REASON)] == "Too many retries"
        assert doc[str(DLQFields.LAST_ERROR)] == "Connection timeout"
        assert doc["custom_field"] == "value"
        assert str(DLQFields.LAST_UPDATED) in doc

    def test_update_to_mongo_minimal(self):
        """Test converting minimal DLQ message update to MongoDB update document."""
        update = DLQMessageUpdate(status=DLQMessageStatus.DISCARDED)

        doc = DLQMapper.update_to_mongo(update)

        assert doc[str(DLQFields.STATUS)] == DLQMessageStatus.DISCARDED
        assert str(DLQFields.LAST_UPDATED) in doc
        assert str(DLQFields.RETRY_COUNT) not in doc
        assert str(DLQFields.NEXT_RETRY_AT) not in doc

    def test_filter_to_query_full(self):
        """Test converting DLQ message filter to MongoDB query."""
        f = DLQMessageFilter(
            status=DLQMessageStatus.PENDING,
            topic="test-topic",
            event_type=EventType.EXECUTION_REQUESTED,
        )

        query = DLQMapper.filter_to_query(f)

        assert query[DLQFields.STATUS] == DLQMessageStatus.PENDING
        assert query[DLQFields.ORIGINAL_TOPIC] == "test-topic"
        assert query[DLQFields.EVENT_TYPE] == EventType.EXECUTION_REQUESTED

    def test_filter_to_query_empty(self):
        """Test converting empty DLQ message filter to MongoDB query."""
        f = DLQMessageFilter()

        query = DLQMapper.filter_to_query(f)

        assert query == {}
