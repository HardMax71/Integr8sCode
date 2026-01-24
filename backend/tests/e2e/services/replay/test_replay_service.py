import pytest
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay.exceptions import ReplaySessionNotFoundError
from app.services.event_replay import ReplayConfig, ReplayFilter
from app.services.replay_service import ReplayService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


class TestCreateSession:
    """Tests for create_session_from_config method."""

    @pytest.mark.asyncio
    async def test_create_session_execution_type(
        self, scope: AsyncContainer
    ) -> None:
        """Create replay session for execution events."""
        svc: ReplayService = await scope.get(ReplayService)

        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1,
        )
        result = await svc.create_session_from_config(cfg)

        assert result.session_id is not None
        # Newly created session has CREATED status
        assert result.status == ReplayStatus.CREATED
        assert result.message is not None

    @pytest.mark.asyncio
    async def test_create_session_with_max_events(
        self, scope: AsyncContainer
    ) -> None:
        """Create session with event limit."""
        svc: ReplayService = await scope.get(ReplayService)

        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=100,
        )
        result = await svc.create_session_from_config(cfg)

        assert result.session_id is not None
        assert result.status == ReplayStatus.CREATED

    @pytest.mark.asyncio
    async def test_create_session_with_filter(
        self, scope: AsyncContainer
    ) -> None:
        """Create session with event filter."""
        svc: ReplayService = await scope.get(ReplayService)

        replay_filter = ReplayFilter(
            aggregate_id="exec-1",
        )
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=replay_filter,
            max_events=10,
        )
        result = await svc.create_session_from_config(cfg)

        assert result.session_id is not None


class TestListSessions:
    """Tests for list_sessions method."""

    @pytest.mark.asyncio
    async def test_list_sessions(self, scope: AsyncContainer) -> None:
        """List replay sessions."""
        svc: ReplayService = await scope.get(ReplayService)

        # Create a session first
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1,
        )
        created = await svc.create_session_from_config(cfg)

        # List sessions
        sessions = svc.list_sessions(limit=10)

        assert isinstance(sessions, list)
        assert any(s.session_id == created.session_id for s in sessions)

    @pytest.mark.asyncio
    async def test_list_sessions_with_limit(self, scope: AsyncContainer) -> None:
        """List sessions respects limit."""
        svc: ReplayService = await scope.get(ReplayService)

        sessions = svc.list_sessions(limit=5)

        assert isinstance(sessions, list)
        assert len(sessions) <= 5


class TestGetSession:
    """Tests for get_session method."""

    @pytest.mark.asyncio
    async def test_get_session_by_id(self, scope: AsyncContainer) -> None:
        """Get session by ID."""
        svc: ReplayService = await scope.get(ReplayService)

        # Create a session
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1,
        )
        created = await svc.create_session_from_config(cfg)

        # Get session
        session = svc.get_session(created.session_id)

        assert session is not None
        assert session.session_id == created.session_id

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, scope: AsyncContainer) -> None:
        """Get nonexistent session raises error."""
        svc: ReplayService = await scope.get(ReplayService)

        with pytest.raises(ReplaySessionNotFoundError):
            svc.get_session("nonexistent-session-id")


class TestCancelSession:
    """Tests for cancel_session method."""

    @pytest.mark.asyncio
    async def test_cancel_session(self, scope: AsyncContainer) -> None:
        """Cancel a replay session."""
        svc: ReplayService = await scope.get(ReplayService)

        # Create a session
        cfg = ReplayConfig(
            replay_type=ReplayType.EXECUTION,
            target=ReplayTarget.TEST,
            filter=ReplayFilter(),
            max_events=1000,  # Large limit so it doesn't complete immediately
        )
        created = await svc.create_session_from_config(cfg)

        # Cancel session
        result = await svc.cancel_session(created.session_id)

        assert result.session_id == created.session_id
        assert result.status == ReplayStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_session(
        self, scope: AsyncContainer
    ) -> None:
        """Cancel nonexistent session raises error."""
        svc: ReplayService = await scope.get(ReplayService)

        with pytest.raises(ReplaySessionNotFoundError):
            await svc.cancel_session("nonexistent-session-id")
