"""Tests for replay API mapper."""

from datetime import datetime, timezone

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayConfig, ReplayFilter, ReplaySessionState
from app.infrastructure.mappers.replay_api_mapper import ReplayApiMapper
from app.schemas_pydantic.replay import ReplayRequest


@pytest.fixture
def sample_filter():
    """Create a sample replay filter."""
    return ReplayFilter(
        execution_id="exec-123",
        event_types=[EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED],
        start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
        user_id="user-456",
        service_name="test-service",
        custom_query={"status": "completed"},
        exclude_event_types=[EventType.EXECUTION_FAILED],
    )


@pytest.fixture
def sample_config(sample_filter):
    """Create a sample replay config."""
    return ReplayConfig(
        replay_type=ReplayType.EXECUTION,
        target=ReplayTarget.KAFKA,
        filter=sample_filter,
        speed_multiplier=2.0,
        preserve_timestamps=True,
        batch_size=100,
        max_events=1000,
        target_topics={EventType.EXECUTION_REQUESTED: "test-topic"},
        target_file_path="/tmp/replay.json",
        skip_errors=True,
        retry_failed=False,
        retry_attempts=3,
        enable_progress_tracking=True,
    )


@pytest.fixture
def sample_session_state(sample_config):
    """Create a sample replay session state."""
    return ReplaySessionState(
        session_id="session-789",
        config=sample_config,
        status=ReplayStatus.RUNNING,
        total_events=500,
        replayed_events=250,
        failed_events=5,
        skipped_events=10,
        created_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        started_at=datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 10, 11, 0, tzinfo=timezone.utc),
        last_event_at=datetime(2024, 1, 1, 10, 10, 30, tzinfo=timezone.utc),
        errors=[{"error": "Error 1", "timestamp": "2024-01-01T10:05:00"}, {"error": "Error 2", "timestamp": "2024-01-01T10:06:00"}],
    )


class TestReplayApiMapper:
    """Test replay API mapper."""

    def test_filter_to_schema_full(self, sample_filter):
        """Test converting replay filter to schema with all fields."""
        schema = ReplayApiMapper.filter_to_schema(sample_filter)

        assert schema.execution_id == "exec-123"
        assert schema.event_types == ["execution_requested", "execution_completed"]
        assert schema.start_time == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert schema.end_time == datetime(2024, 1, 31, tzinfo=timezone.utc)
        assert schema.user_id == "user-456"
        assert schema.service_name == "test-service"
        assert schema.custom_query == {"status": "completed"}
        assert schema.exclude_event_types == ["execution_failed"]

    def test_filter_to_schema_minimal(self):
        """Test converting minimal replay filter to schema."""
        filter_obj = ReplayFilter()

        schema = ReplayApiMapper.filter_to_schema(filter_obj)

        assert schema.execution_id is None
        assert schema.event_types is None
        assert schema.start_time is None
        assert schema.end_time is None
        assert schema.user_id is None
        assert schema.service_name is None
        assert schema.custom_query is None
        assert schema.exclude_event_types is None

    def test_filter_to_schema_no_event_types(self):
        """Test converting replay filter with no event types."""
        filter_obj = ReplayFilter(
            execution_id="exec-456",
            event_types=None,
            exclude_event_types=None,
        )

        schema = ReplayApiMapper.filter_to_schema(filter_obj)

        assert schema.execution_id == "exec-456"
        assert schema.event_types is None
        assert schema.exclude_event_types is None

    def test_config_to_schema_full(self, sample_config):
        """Test converting replay config to schema with all fields."""
        schema = ReplayApiMapper.config_to_schema(sample_config)

        assert schema.replay_type == ReplayType.EXECUTION
        assert schema.target == ReplayTarget.KAFKA
        assert schema.filter is not None
        assert schema.filter.execution_id == "exec-123"
        assert schema.speed_multiplier == 2.0
        assert schema.preserve_timestamps is True
        assert schema.batch_size == 100
        assert schema.max_events == 1000
        assert schema.target_topics == {"execution_requested": "test-topic"}
        assert schema.target_file_path == "/tmp/replay.json"
        assert schema.skip_errors is True
        assert schema.retry_failed is False
        assert schema.retry_attempts == 3
        assert schema.enable_progress_tracking is True

    def test_config_to_schema_minimal(self):
        """Test converting minimal replay config to schema."""
        config = ReplayConfig(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.FILE,
            filter=ReplayFilter(),
        )

        schema = ReplayApiMapper.config_to_schema(config)

        assert schema.replay_type == ReplayType.TIME_RANGE
        assert schema.target == ReplayTarget.FILE
        assert schema.filter is not None
        # Default values from ReplayConfig
        assert schema.speed_multiplier == 1.0
        assert schema.preserve_timestamps is False
        assert schema.batch_size == 100
        assert schema.max_events is None
        assert schema.target_topics == {}
        assert schema.target_file_path is None
        assert schema.skip_errors is True
        assert schema.retry_failed is False
        assert schema.retry_attempts == 3
        assert schema.enable_progress_tracking is True

    def test_config_to_schema_no_target_topics(self):
        """Test converting replay config with no target topics."""
        config = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
            target_topics=None,
        )

        schema = ReplayApiMapper.config_to_schema(config)

        assert schema.target_topics == {}

    def test_session_to_response(self, sample_session_state):
        """Test converting session state to response."""
        response = ReplayApiMapper.session_to_response(sample_session_state)

        assert response.session_id == "session-789"
        assert response.config is not None
        assert response.config.replay_type == ReplayType.EXECUTION
        assert response.status == ReplayStatus.RUNNING
        assert response.total_events == 500
        assert response.replayed_events == 250
        assert response.failed_events == 5
        assert response.skipped_events == 10
        assert response.created_at == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert response.started_at == datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc)
        assert response.completed_at == datetime(2024, 1, 1, 10, 11, 0, tzinfo=timezone.utc)
        assert response.last_event_at == datetime(2024, 1, 1, 10, 10, 30, tzinfo=timezone.utc)
        assert response.errors == [{"error": "Error 1", "timestamp": "2024-01-01T10:05:00"}, {"error": "Error 2", "timestamp": "2024-01-01T10:06:00"}]

    def test_session_to_summary_with_duration(self, sample_session_state):
        """Test converting session state to summary with duration calculation."""
        summary = ReplayApiMapper.session_to_summary(sample_session_state)

        assert summary.session_id == "session-789"
        assert summary.replay_type == ReplayType.EXECUTION
        assert summary.target == ReplayTarget.KAFKA
        assert summary.status == ReplayStatus.RUNNING
        assert summary.total_events == 500
        assert summary.replayed_events == 250
        assert summary.failed_events == 5
        assert summary.skipped_events == 10
        assert summary.created_at == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert summary.started_at == datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc)
        assert summary.completed_at == datetime(2024, 1, 1, 10, 11, 0, tzinfo=timezone.utc)

        # Duration should be 600 seconds (10 minutes)
        assert summary.duration_seconds == 600.0

        # Throughput should be 250 events / 600 seconds
        assert summary.throughput_events_per_second == pytest.approx(250 / 600.0)

    def test_session_to_summary_no_duration(self):
        """Test converting session state to summary without completed time."""
        state = ReplaySessionState(
            session_id="session-001",
            config=ReplayConfig(
                replay_type=ReplayType.TIME_RANGE,
                target=ReplayTarget.FILE,
                filter=ReplayFilter(),
            ),
            status=ReplayStatus.RUNNING,
            total_events=100,
            replayed_events=50,
            failed_events=0,
            skipped_events=0,
            created_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
            completed_at=None,  # Not completed yet
        )

        summary = ReplayApiMapper.session_to_summary(state)

        assert summary.duration_seconds is None
        assert summary.throughput_events_per_second is None

    def test_session_to_summary_zero_duration(self):
        """Test converting session state with zero duration."""
        now = datetime.now(timezone.utc)
        state = ReplaySessionState(
            session_id="session-002",
            config=ReplayConfig(
                replay_type=ReplayType.TIME_RANGE,
                target=ReplayTarget.FILE,
                filter=ReplayFilter(),
            ),
            status=ReplayStatus.COMPLETED,
            total_events=0,
            replayed_events=0,
            failed_events=0,
            skipped_events=0,
            created_at=now,
            started_at=now,
            completed_at=now,  # Same time as started
        )

        summary = ReplayApiMapper.session_to_summary(state)

        assert summary.duration_seconds == 0.0
        # Throughput should be None when duration is 0
        assert summary.throughput_events_per_second is None

    def test_session_to_summary_no_start_time(self):
        """Test converting session state without start time."""
        state = ReplaySessionState(
            session_id="session-003",
            config=ReplayConfig(
                replay_type=ReplayType.TIME_RANGE,
                target=ReplayTarget.FILE,
                filter=ReplayFilter(),
            ),
            status=ReplayStatus.CREATED,
            total_events=100,
            replayed_events=0,
            failed_events=0,
            skipped_events=0,
            created_at=datetime.now(timezone.utc),
            started_at=None,  # Not started yet
            completed_at=None,
        )

        summary = ReplayApiMapper.session_to_summary(state)

        assert summary.duration_seconds is None
        assert summary.throughput_events_per_second is None

    def test_request_to_filter_full(self):
        """Test converting replay request to filter with all fields."""
        request = ReplayRequest(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.KAFKA,
            execution_id="exec-999",
            event_types=[EventType.EXECUTION_REQUESTED],
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
            user_id="user-999",
            service_name="service-999",
        )

        filter_obj = ReplayApiMapper.request_to_filter(request)

        assert filter_obj.execution_id == "exec-999"
        assert filter_obj.event_types == [EventType.EXECUTION_REQUESTED]
        assert filter_obj.start_time == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert filter_obj.end_time == datetime(2024, 1, 31, tzinfo=timezone.utc)
        assert filter_obj.user_id == "user-999"
        assert filter_obj.service_name == "service-999"

    def test_request_to_filter_with_none_times(self):
        """Test converting replay request with None times."""
        request = ReplayRequest(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.FILE,
            start_time=None,
            end_time=None,
        )

        filter_obj = ReplayApiMapper.request_to_filter(request)

        assert filter_obj.start_time is None
        assert filter_obj.end_time is None

    def test_request_to_config_full(self):
        """Test converting replay request to config with all fields."""
        request = ReplayRequest(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.KAFKA,
            execution_id="exec-888",
            event_types=[EventType.EXECUTION_COMPLETED],
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 31, tzinfo=timezone.utc),
            user_id="user-888",
            service_name="service-888",
            speed_multiplier=3.0,
            preserve_timestamps=False,
            batch_size=50,
            max_events=500,
            skip_errors=False,
            target_file_path="/tmp/output.json",
        )

        config = ReplayApiMapper.request_to_config(request)

        assert config.replay_type == ReplayType.EXECUTION
        assert config.target == ReplayTarget.KAFKA
        assert config.filter.execution_id == "exec-888"
        assert config.filter.event_types == [EventType.EXECUTION_COMPLETED]
        assert config.speed_multiplier == 3.0
        assert config.preserve_timestamps is False
        assert config.batch_size == 50
        assert config.max_events == 500
        assert config.skip_errors is False
        assert config.target_file_path == "/tmp/output.json"

    def test_request_to_config_minimal(self):
        """Test converting minimal replay request to config."""
        request = ReplayRequest(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.FILE,
        )

        config = ReplayApiMapper.request_to_config(request)

        assert config.replay_type == ReplayType.TIME_RANGE
        assert config.target == ReplayTarget.FILE
        assert config.filter is not None
        # Default values from ReplayConfig
        assert config.speed_multiplier == 1.0
        assert config.preserve_timestamps == False
        assert config.batch_size == 100
        assert config.max_events is None
        assert config.skip_errors == True
        assert config.target_file_path is None

    def test_op_to_response(self):
        """Test converting operation to response."""
        response = ReplayApiMapper.op_to_response(
            session_id="session-777",
            status=ReplayStatus.COMPLETED,
            message="Replay completed successfully",
        )

        assert response.session_id == "session-777"
        assert response.status == ReplayStatus.COMPLETED
        assert response.message == "Replay completed successfully"

    def test_cleanup_to_response(self):
        """Test converting cleanup to response."""
        response = ReplayApiMapper.cleanup_to_response(
            removed_sessions=5,
            message="Cleaned up 5 old sessions",
        )

        assert response.removed_sessions == 5
        assert response.message == "Cleaned up 5 old sessions"
