import pytest

from app.domain.enums import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplaySessionNotFoundError
from app.services.event_replay import EventReplayService, ReplayConfig, ReplayFilter

pytestmark = [pytest.mark.e2e]


class TestCreateSession:
    """Tests for create_session_from_config method."""

    async def test_create_session_execution_type(self, event_replay_service: EventReplayService) -> None:
        """Create replay session for execution events."""

        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1,
        )
        result = await event_replay_service.create_session_from_config(cfg)

        assert result.session_id is not None
        # Newly created session has CREATED status
        assert result.status == ReplayStatus.CREATED
        assert result.message is not None

    async def test_create_session_with_max_events(self, event_replay_service: EventReplayService) -> None:
        """Create session with event limit."""

        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=100,
        )
        result = await event_replay_service.create_session_from_config(cfg)

        assert result.session_id is not None
        assert result.status == ReplayStatus.CREATED

    async def test_create_session_with_filter(self, event_replay_service: EventReplayService) -> None:
        """Create session with event filter."""

        replay_filter = ReplayFilter(
            aggregate_id="exec-1",
        )
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=replay_filter,
            max_events=10,
        )
        result = await event_replay_service.create_session_from_config(cfg)

        assert result.session_id is not None


class TestListSessions:
    """Tests for list_sessions method."""

    async def test_list_sessions(self, event_replay_service: EventReplayService) -> None:
        """List replay sessions."""

        # Create a session first
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1,
        )
        created = await event_replay_service.create_session_from_config(cfg)

        # List sessions
        sessions = event_replay_service.list_sessions(limit=10)

        assert isinstance(sessions, list)
        assert any(s.session_id == created.session_id for s in sessions)

    async def test_list_sessions_with_limit(self, event_replay_service: EventReplayService) -> None:
        """List sessions respects limit."""

        sessions = event_replay_service.list_sessions(limit=5)

        assert isinstance(sessions, list)
        assert len(sessions) <= 5


class TestGetSession:
    """Tests for get_session method."""

    async def test_get_session_by_id(self, event_replay_service: EventReplayService) -> None:
        """Get session by ID."""

        # Create a session
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1,
        )
        created = await event_replay_service.create_session_from_config(cfg)

        # Get session
        session = event_replay_service.get_session(created.session_id)

        assert session is not None
        assert session.session_id == created.session_id

    async def test_get_session_not_found(self, event_replay_service: EventReplayService) -> None:
        """Get nonexistent session raises error."""

        with pytest.raises(ReplaySessionNotFoundError):
            event_replay_service.get_session("nonexistent-session-id")


class TestCancelSession:
    """Tests for cancel_session method."""

    async def test_cancel_session(self, event_replay_service: EventReplayService) -> None:
        """Cancel a replay session."""

        # Create a session
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1000,  # Large limit so it doesn't complete immediately
        )
        created = await event_replay_service.create_session_from_config(cfg)

        # Cancel session
        result = await event_replay_service.cancel_session(created.session_id)

        assert result.session_id == created.session_id
        assert result.status == ReplayStatus.CANCELLED

    async def test_cancel_nonexistent_session(self, event_replay_service: EventReplayService) -> None:
        """Cancel nonexistent session raises error."""

        with pytest.raises(ReplaySessionNotFoundError):
            await event_replay_service.cancel_session("nonexistent-session-id")
