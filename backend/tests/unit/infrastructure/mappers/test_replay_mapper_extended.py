"""Extended tests for replay mapper to achieve 95%+ coverage."""

from datetime import datetime, timezone
from typing import Any

import pytest

from app.domain.admin import (
    ReplayQuery,
    ReplaySession,
    ReplaySessionData,
    ReplaySessionStatusDetail,
    ReplaySessionStatusInfo,
)
from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.events.event_models import EventSummary
from app.domain.replay import ReplayConfig, ReplayFilter, ReplaySessionState
from app.infrastructure.mappers.replay_mapper import (
    ReplayApiMapper,
    ReplayQueryMapper,
    ReplaySessionDataMapper,
    ReplaySessionMapper,
    ReplayStateMapper,
)
from app.schemas_pydantic.admin_events import EventReplayRequest


@pytest.fixture
def sample_replay_session():
    """Create a sample replay session with all optional fields."""
    return ReplaySession(
        session_id="session-123",
        type="replay_session",
        status=ReplayStatus.RUNNING,
        total_events=100,
        replayed_events=50,
        failed_events=5,
        skipped_events=10,
        correlation_id="corr-456",
        created_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        started_at=datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
        error="Some error occurred",
        created_by="admin-user",
        target_service="test-service",
        dry_run=False,
        triggered_executions=["exec-1", "exec-2"],
    )


@pytest.fixture
def minimal_replay_session():
    """Create a minimal replay session without optional fields."""
    return ReplaySession(
        session_id="session-456",
        status=ReplayStatus.SCHEDULED,
        total_events=10,
        correlation_id="corr-789",
        created_at=datetime.now(timezone.utc),
        dry_run=True,
    )


@pytest.fixture
def sample_replay_config():
    """Create a sample replay config."""
    return ReplayConfig(
        replay_type=ReplayType.EXECUTION,
        target=ReplayTarget.KAFKA,
        filter=ReplayFilter(
            execution_id="exec-123",
            event_types=[EventType.EXECUTION_REQUESTED],
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
        ),
        speed_multiplier=2.0,
        preserve_timestamps=True,
        batch_size=100,
        max_events=1000,
    )


@pytest.fixture
def sample_replay_session_state(sample_replay_config):
    """Create a sample replay session state."""
    return ReplaySessionState(
        session_id="state-123",
        config=sample_replay_config,
        status=ReplayStatus.RUNNING,
        total_events=500,
        replayed_events=250,
        failed_events=10,
        skipped_events=5,
        created_at=datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
        started_at=datetime(2024, 1, 1, 9, 1, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 9, 30, 0, tzinfo=timezone.utc),
        last_event_at=datetime(2024, 1, 1, 9, 29, 30, tzinfo=timezone.utc),
        errors=["Error 1", "Error 2"],
    )


class TestReplaySessionMapper:
    """Extended tests for ReplaySessionMapper."""

    def test_to_dict_with_all_optional_fields(self, sample_replay_session):
        """Test converting session to dict with all optional fields present."""
        result = ReplaySessionMapper.to_dict(sample_replay_session)

        assert result["session_id"] == "session-123"
        assert result["started_at"] == sample_replay_session.started_at
        assert result["completed_at"] == sample_replay_session.completed_at
        assert result["error"] == "Some error occurred"
        assert result["created_by"] == "admin-user"
        assert result["target_service"] == "test-service"
        assert result["triggered_executions"] == ["exec-1", "exec-2"]

    def test_to_dict_without_optional_fields(self, minimal_replay_session):
        """Test converting session to dict without optional fields."""
        result = ReplaySessionMapper.to_dict(minimal_replay_session)

        assert result["session_id"] == "session-456"
        assert "started_at" not in result
        assert "completed_at" not in result
        assert "error" not in result
        assert "created_by" not in result
        assert "target_service" not in result

    def test_from_dict_with_missing_fields(self):
        """Test creating session from dict with missing fields."""
        data = {}  # Minimal data

        session = ReplaySessionMapper.from_dict(data)

        assert session.session_id == ""
        assert session.type == "replay_session"
        assert session.status == ReplayStatus.SCHEDULED
        assert session.total_events == 0
        assert session.replayed_events == 0
        assert session.failed_events == 0
        assert session.skipped_events == 0
        assert session.correlation_id == ""
        assert session.dry_run is False
        assert session.triggered_executions == []

    def test_status_detail_to_dict_without_estimated_completion(self, sample_replay_session):
        """Test converting status detail without estimated_completion."""
        detail = ReplaySessionStatusDetail(
            session=sample_replay_session,
            estimated_completion=None,  # No estimated completion
            execution_results={"success": 10, "failed": 2},
        )

        result = ReplaySessionMapper.status_detail_to_dict(detail)

        assert result["session_id"] == "session-123"
        assert "estimated_completion" not in result
        assert result["execution_results"] == {"success": 10, "failed": 2}

    def test_status_detail_to_dict_with_estimated_completion(self, sample_replay_session):
        """Test converting status detail with estimated_completion."""
        estimated = datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        detail = ReplaySessionStatusDetail(
            session=sample_replay_session,
            estimated_completion=estimated,
        )

        result = ReplaySessionMapper.status_detail_to_dict(detail)

        assert result["estimated_completion"] == estimated

    def test_to_status_info(self, sample_replay_session):
        """Test converting session to status info."""
        info = ReplaySessionMapper.to_status_info(sample_replay_session)

        assert isinstance(info, ReplaySessionStatusInfo)
        assert info.session_id == sample_replay_session.session_id
        assert info.status == sample_replay_session.status
        assert info.total_events == sample_replay_session.total_events
        assert info.replayed_events == sample_replay_session.replayed_events
        assert info.failed_events == sample_replay_session.failed_events
        assert info.skipped_events == sample_replay_session.skipped_events
        assert info.correlation_id == sample_replay_session.correlation_id
        assert info.created_at == sample_replay_session.created_at
        assert info.started_at == sample_replay_session.started_at
        assert info.completed_at == sample_replay_session.completed_at
        assert info.error == sample_replay_session.error
        assert info.progress_percentage == sample_replay_session.progress_percentage


class TestReplayQueryMapper:
    """Extended tests for ReplayQueryMapper."""

    def test_to_mongodb_query_with_start_time_only(self):
        """Test query with only start_time."""
        query = ReplayQuery(
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )

        result = ReplayQueryMapper.to_mongodb_query(query)

        assert "timestamp" in result
        assert "$gte" in result["timestamp"]
        assert "$lte" not in result["timestamp"]

    def test_to_mongodb_query_with_end_time_only(self):
        """Test query with only end_time."""
        query = ReplayQuery(
            end_time=datetime(2024, 12, 31, tzinfo=timezone.utc)
        )

        result = ReplayQueryMapper.to_mongodb_query(query)

        assert "timestamp" in result
        assert "$lte" in result["timestamp"]
        assert "$gte" not in result["timestamp"]

    def test_to_mongodb_query_empty(self):
        """Test empty query."""
        query = ReplayQuery()

        result = ReplayQueryMapper.to_mongodb_query(query)

        assert result == {}


class TestReplaySessionDataMapper:
    """Extended tests for ReplaySessionDataMapper."""

    def test_to_dict_without_events_preview(self):
        """Test converting data without events preview."""
        data = ReplaySessionData(
            dry_run=False,  # Not dry run
            total_events=50,
            replay_correlation_id="replay-corr-123",
            query={"status": "completed"},
            events_preview=None,
        )

        result = ReplaySessionDataMapper.to_dict(data)

        assert result["dry_run"] is False
        assert result["total_events"] == 50
        assert result["replay_correlation_id"] == "replay-corr-123"
        assert result["query"] == {"status": "completed"}
        assert "events_preview" not in result

    def test_to_dict_dry_run_without_preview(self):
        """Test dry run but no events preview."""
        data = ReplaySessionData(
            dry_run=True,
            total_events=20,
            replay_correlation_id="dry-corr-456",
            query={"type": "test"},
            events_preview=None,  # No preview even though dry run
        )

        result = ReplaySessionDataMapper.to_dict(data)

        assert result["dry_run"] is True
        assert "events_preview" not in result

    def test_to_dict_with_events_preview(self):
        """Test converting data with events preview."""
        events = [
            EventSummary(
                event_id="event-1",
                event_type="type-1",
                timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                aggregate_id="agg-1",
            ),
            EventSummary(
                event_id="event-2",
                event_type="type-2",
                timestamp=datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc),
                aggregate_id=None,  # No aggregate_id
            ),
        ]

        data = ReplaySessionData(
            dry_run=True,
            total_events=2,
            replay_correlation_id="preview-corr",
            query={},
            events_preview=events,
        )

        result = ReplaySessionDataMapper.to_dict(data)

        assert result["dry_run"] is True
        assert len(result["events_preview"]) == 2
        assert result["events_preview"][0]["event_id"] == "event-1"
        assert result["events_preview"][0]["aggregate_id"] == "agg-1"
        assert result["events_preview"][1]["event_id"] == "event-2"
        assert result["events_preview"][1]["aggregate_id"] is None


class TestReplayApiMapper:
    """Tests for ReplayApiMapper."""

    def test_request_to_query_full(self):
        """Test converting full request to query."""
        request = EventReplayRequest(
            event_ids=["ev-1", "ev-2"],
            correlation_id="api-corr-123",
            aggregate_id="api-agg-456",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
        )

        query = ReplayApiMapper.request_to_query(request)

        assert query.event_ids == ["ev-1", "ev-2"]
        assert query.correlation_id == "api-corr-123"
        assert query.aggregate_id == "api-agg-456"
        assert query.start_time == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert query.end_time == datetime(2024, 1, 31, tzinfo=timezone.utc)

    def test_request_to_query_minimal(self):
        """Test converting minimal request to query."""
        request = EventReplayRequest()

        query = ReplayApiMapper.request_to_query(request)

        assert query.event_ids is None
        assert query.correlation_id is None
        assert query.aggregate_id is None
        assert query.start_time is None
        assert query.end_time is None


class TestReplayStateMapper:
    """Tests for ReplayStateMapper."""

    def test_to_mongo_document_full(self, sample_replay_session_state):
        """Test converting session state to mongo document with all fields."""
        doc = ReplayStateMapper.to_mongo_document(sample_replay_session_state)

        assert doc["session_id"] == "state-123"
        assert doc["status"] == ReplayStatus.RUNNING
        assert doc["total_events"] == 500
        assert doc["replayed_events"] == 250
        assert doc["failed_events"] == 10
        assert doc["skipped_events"] == 5
        assert doc["created_at"] == sample_replay_session_state.created_at
        assert doc["started_at"] == sample_replay_session_state.started_at
        assert doc["completed_at"] == sample_replay_session_state.completed_at
        assert doc["last_event_at"] == sample_replay_session_state.last_event_at
        assert doc["errors"] == ["Error 1", "Error 2"]
        assert "config" in doc

    def test_to_mongo_document_minimal(self):
        """Test converting minimal session state to mongo document."""
        minimal_state = ReplaySessionState(
            session_id="minimal-123",
            config=ReplayConfig(
                replay_type=ReplayType.TIME_RANGE,
                target=ReplayTarget.FILE,
                filter=ReplayFilter(),
            ),
            status=ReplayStatus.SCHEDULED,
        )

        doc = ReplayStateMapper.to_mongo_document(minimal_state)

        assert doc["session_id"] == "minimal-123"
        assert doc["status"] == ReplayStatus.SCHEDULED
        assert doc["total_events"] == 0
        assert doc["replayed_events"] == 0
        assert doc["failed_events"] == 0
        assert doc["skipped_events"] == 0
        assert doc["started_at"] is None
        assert doc["completed_at"] is None
        assert doc["last_event_at"] is None
        assert doc["errors"] == []

    def test_to_mongo_document_without_attributes(self):
        """Test converting object without expected attributes."""
        # Create a mock object without some attributes
        class MockSession:
            session_id = "mock-123"
            config = ReplayConfig(
                replay_type=ReplayType.TIME_RANGE,
                target=ReplayTarget.FILE,
                filter=ReplayFilter(),
            )
            status = ReplayStatus.RUNNING
            created_at = datetime.now(timezone.utc)

        mock_session = MockSession()
        doc = ReplayStateMapper.to_mongo_document(mock_session)

        # Should use getattr with defaults
        assert doc["total_events"] == 0
        assert doc["replayed_events"] == 0
        assert doc["failed_events"] == 0
        assert doc["skipped_events"] == 0
        assert doc["started_at"] is None
        assert doc["completed_at"] is None
        assert doc["last_event_at"] is None
        assert doc["errors"] == []

    def test_from_mongo_document_full(self):
        """Test creating session state from full mongo document."""
        doc = {
            "session_id": "from-mongo-123",
            "config": {
                "replay_type": "execution",
                "target": "kafka",
                "filter": {
                    "execution_id": "exec-999",
                    "event_types": ["execution_requested"],
                },
                "speed_multiplier": 3.0,
                "batch_size": 50,
            },
            "status": ReplayStatus.COMPLETED,
            "total_events": 100,
            "replayed_events": 100,
            "failed_events": 0,
            "skipped_events": 0,
            "started_at": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            "completed_at": datetime(2024, 1, 1, 10, 10, 0, tzinfo=timezone.utc),
            "last_event_at": datetime(2024, 1, 1, 10, 9, 50, tzinfo=timezone.utc),
            "errors": ["Warning 1"],
        }

        state = ReplayStateMapper.from_mongo_document(doc)

        assert state.session_id == "from-mongo-123"
        assert state.status == ReplayStatus.COMPLETED
        assert state.total_events == 100
        assert state.replayed_events == 100
        assert state.failed_events == 0
        assert state.skipped_events == 0
        assert state.started_at == doc["started_at"]
        assert state.completed_at == doc["completed_at"]
        assert state.last_event_at == doc["last_event_at"]
        assert state.errors == ["Warning 1"]

    def test_from_mongo_document_minimal(self):
        """Test creating session state from minimal mongo document."""
        doc = {
            "config": {
                "replay_type": "time_range",
                "target": "kafka",
                "filter": {},  # Empty filter is valid
            }
        }  # Minimal valid document

        state = ReplayStateMapper.from_mongo_document(doc)

        assert state.session_id == ""
        assert state.status == ReplayStatus.SCHEDULED  # Default
        assert state.total_events == 0
        assert state.replayed_events == 0
        assert state.failed_events == 0
        assert state.skipped_events == 0
        assert state.started_at is None
        assert state.completed_at is None
        assert state.last_event_at is None
        assert state.errors == []

    def test_from_mongo_document_with_string_status(self):
        """Test creating session state with string status."""
        doc = {
            "session_id": "string-status-123",
            "status": "running",  # String instead of enum
            "config": {
                "replay_type": "time_range",
                "target": "kafka",
                "filter": {},
            },
        }

        state = ReplayStateMapper.from_mongo_document(doc)

        assert state.status == ReplayStatus.RUNNING

    def test_from_mongo_document_with_enum_status(self):
        """Test creating session state with enum status."""
        doc = {
            "session_id": "enum-status-123",
            "status": ReplayStatus.FAILED,  # Already an enum
            "config": {
                "replay_type": "execution",
                "target": "kafka",
                "filter": {},
            },
        }

        state = ReplayStateMapper.from_mongo_document(doc)

        assert state.status == ReplayStatus.FAILED