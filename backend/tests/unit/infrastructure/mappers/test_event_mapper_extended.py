"""Extended tests for event mapper to achieve 95%+ coverage."""

from datetime import datetime, timezone

import pytest

from app.domain.events.event_models import (
    ArchivedEvent,
    Event,
    EventExportRow,
    EventFields,
    EventFilter,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.mappers.event_mapper import (
    ArchivedEventMapper,
    EventExportRowMapper,
    EventFilterMapper,
    EventMapper,
)


@pytest.fixture
def sample_metadata():
    """Create sample event metadata."""
    return EventMetadata(
        service_name="test-service",
        service_version="1.0.0",
        correlation_id="corr-123",
        user_id="user-456",
        request_id="req-789",
    )


@pytest.fixture
def sample_event(sample_metadata):
    """Create a sample event with all optional fields."""
    return Event(
        event_id="event-123",
        event_type="test.event",
        event_version="2.0",
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        metadata=sample_metadata,
        payload={"key": "value", "nested": {"data": 123}},
        aggregate_id="agg-456",
        stored_at=datetime(2024, 1, 15, 10, 30, 1, tzinfo=timezone.utc),
        ttl_expires_at=datetime(2024, 2, 15, 10, 30, 0, tzinfo=timezone.utc),
        status="processed",
        error="Some error occurred",
    )


@pytest.fixture
def minimal_event():
    """Create a minimal event without optional fields."""
    return Event(
        event_id="event-minimal",
        event_type="minimal.event",
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata=EventMetadata(service_name="minimal-service", service_version="1.0.0"),
        payload={},
    )


class TestEventMapper:
    """Test EventMapper with all branches."""

    def test_to_mongo_document_with_all_fields(self, sample_event):
        """Test converting event to MongoDB document with all optional fields."""
        doc = EventMapper.to_mongo_document(sample_event)

        assert doc[EventFields.EVENT_ID] == "event-123"
        assert doc[EventFields.EVENT_TYPE] == "test.event"
        assert doc[EventFields.EVENT_VERSION] == "2.0"
        assert doc[EventFields.TIMESTAMP] == sample_event.timestamp
        assert doc[EventFields.PAYLOAD] == {"key": "value", "nested": {"data": 123}}
        assert doc[EventFields.AGGREGATE_ID] == "agg-456"
        assert doc[EventFields.STORED_AT] == sample_event.stored_at
        assert doc[EventFields.TTL_EXPIRES_AT] == sample_event.ttl_expires_at
        assert doc[EventFields.STATUS] == "processed"
        assert doc[EventFields.ERROR] == "Some error occurred"

    def test_to_mongo_document_minimal(self, minimal_event):
        """Test converting minimal event to MongoDB document."""
        doc = EventMapper.to_mongo_document(minimal_event)

        assert doc[EventFields.EVENT_ID] == "event-minimal"
        assert doc[EventFields.EVENT_TYPE] == "minimal.event"
        assert EventFields.AGGREGATE_ID not in doc
        assert EventFields.STORED_AT not in doc
        assert EventFields.TTL_EXPIRES_AT not in doc
        assert EventFields.STATUS not in doc
        assert EventFields.ERROR not in doc


class TestArchivedEventMapper:
    """Test ArchivedEventMapper with all branches."""

    def test_to_mongo_document_with_all_fields(self, sample_event):
        """Test converting archived event with all deletion fields."""
        archived = ArchivedEvent(
            event_id=sample_event.event_id,
            event_type=sample_event.event_type,
            event_version=sample_event.event_version,
            timestamp=sample_event.timestamp,
            metadata=sample_event.metadata,
            payload=sample_event.payload,
            aggregate_id=sample_event.aggregate_id,
            stored_at=sample_event.stored_at,
            ttl_expires_at=sample_event.ttl_expires_at,
            status=sample_event.status,
            error=sample_event.error,
            deleted_at=datetime(2024, 1, 20, 15, 0, 0, tzinfo=timezone.utc),
            deleted_by="admin-user",
            deletion_reason="Data cleanup",
        )

        doc = ArchivedEventMapper.to_mongo_document(archived)

        assert doc[EventFields.EVENT_ID] == sample_event.event_id
        assert doc[EventFields.DELETED_AT] == archived.deleted_at
        assert doc[EventFields.DELETED_BY] == "admin-user"
        assert doc[EventFields.DELETION_REASON] == "Data cleanup"

    def test_to_mongo_document_minimal_deletion_info(self, minimal_event):
        """Test converting archived event with minimal deletion info."""
        archived = ArchivedEvent(
            event_id=minimal_event.event_id,
            event_type=minimal_event.event_type,
            event_version=minimal_event.event_version,
            timestamp=minimal_event.timestamp,
            metadata=minimal_event.metadata,
            payload=minimal_event.payload,
            deleted_at=None,
            deleted_by=None,
            deletion_reason=None,
        )

        doc = ArchivedEventMapper.to_mongo_document(archived)

        assert doc[EventFields.EVENT_ID] == minimal_event.event_id
        assert EventFields.DELETED_AT not in doc
        assert EventFields.DELETED_BY not in doc
        assert EventFields.DELETION_REASON not in doc


class TestEventFilterMapper:
    """Test EventFilterMapper with all branches."""

    def test_to_mongo_query_full(self):
        """Test converting filter with all fields to MongoDB query."""
        filt = EventFilter(
            event_types=["type1", "type2"],
            aggregate_id="agg-123",
            correlation_id="corr-456",
            user_id="user-789",
            service_name="test-service",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
            text_search="search term",
        )
        # Add status attribute dynamically
        filt.status = "completed"

        query = EventFilterMapper.to_mongo_query(filt)

        assert query[EventFields.EVENT_TYPE] == {"$in": ["type1", "type2"]}
        assert query[EventFields.AGGREGATE_ID] == "agg-123"
        assert query[EventFields.METADATA_CORRELATION_ID] == "corr-456"
        assert query[EventFields.METADATA_USER_ID] == "user-789"
        assert query[EventFields.METADATA_SERVICE_NAME] == "test-service"
        assert query[EventFields.STATUS] == "completed"
        assert query[EventFields.TIMESTAMP]["$gte"] == filt.start_time
        assert query[EventFields.TIMESTAMP]["$lte"] == filt.end_time
        assert query["$text"] == {"$search": "search term"}

    def test_to_mongo_query_with_search_text(self):
        """Test converting filter with search_text field."""
        filt = EventFilter(search_text="another search")

        query = EventFilterMapper.to_mongo_query(filt)

        assert query["$text"] == {"$search": "another search"}

    def test_to_mongo_query_only_start_time(self):
        """Test converting filter with only start_time."""
        filt = EventFilter(
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=None,
        )

        query = EventFilterMapper.to_mongo_query(filt)

        assert query[EventFields.TIMESTAMP] == {"$gte": filt.start_time}

    def test_to_mongo_query_only_end_time(self):
        """Test converting filter with only end_time."""
        filt = EventFilter(
            start_time=None,
            end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
        )

        query = EventFilterMapper.to_mongo_query(filt)

        assert query[EventFields.TIMESTAMP] == {"$lte": filt.end_time}

    def test_to_mongo_query_minimal(self):
        """Test converting minimal filter."""
        filt = EventFilter()

        query = EventFilterMapper.to_mongo_query(filt)

        assert query == {}

    def test_to_mongo_query_with_individual_fields(self):
        """Test converting filter with individual fields set."""
        # Test each field individually to ensure all branches are covered

        # Test with event_types
        filt = EventFilter(event_types=["test"])
        query = EventFilterMapper.to_mongo_query(filt)
        assert EventFields.EVENT_TYPE in query

        # Test with aggregate_id
        filt = EventFilter(aggregate_id="agg-1")
        query = EventFilterMapper.to_mongo_query(filt)
        assert EventFields.AGGREGATE_ID in query

        # Test with correlation_id
        filt = EventFilter(correlation_id="corr-1")
        query = EventFilterMapper.to_mongo_query(filt)
        assert EventFields.METADATA_CORRELATION_ID in query

        # Test with user_id
        filt = EventFilter(user_id="user-1")
        query = EventFilterMapper.to_mongo_query(filt)
        assert EventFields.METADATA_USER_ID in query

        # Test with service_name
        filt = EventFilter(service_name="service-1")
        query = EventFilterMapper.to_mongo_query(filt)
        assert EventFields.METADATA_SERVICE_NAME in query


class TestEventExportRowMapper:
    """Test EventExportRowMapper."""

    def test_from_event_with_all_fields(self, sample_event):
        """Test creating export row from event with all fields."""
        row = EventExportRowMapper.from_event(sample_event)

        assert row.event_id == "event-123"
        assert row.event_type == "test.event"
        assert row.correlation_id == "corr-123"
        assert row.aggregate_id == "agg-456"
        assert row.user_id == "user-456"
        assert row.service == "test-service"
        assert row.status == "processed"
        assert row.error == "Some error occurred"

    def test_from_event_minimal(self, minimal_event):
        """Test creating export row from minimal event."""
        row = EventExportRowMapper.from_event(minimal_event)

        assert row.event_id == "event-minimal"
        assert row.event_type == "minimal.event"
        # correlation_id is auto-generated, so it won't be empty
        assert row.correlation_id != ""
        assert row.aggregate_id == ""
        assert row.user_id == ""
        assert row.service == "minimal-service"
        assert row.status == ""
        assert row.error == ""
