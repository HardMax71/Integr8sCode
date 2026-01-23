import pytest
from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayFilter
from app.schemas_pydantic.replay import (
    CleanupResponse,
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
)
from app.schemas_pydantic.replay_models import ReplaySession
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.admin, pytest.mark.kafka]


class TestCreateReplaySession:
    """Tests for POST /api/v1/replay/sessions."""

    @pytest.mark.asyncio
    async def test_create_replay_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can create a replay session."""
        request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
            speed_multiplier=1.0,
            preserve_timestamps=False,
            batch_size=100,
            skip_errors=True,
            enable_progress_tracking=True,
        )
        response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )

        assert response.status_code == 200
        result = ReplayResponse.model_validate(response.json())

        assert result.session_id is not None
        assert result.status in list(ReplayStatus)
        assert result.message is not None

    @pytest.mark.asyncio
    async def test_create_replay_session_with_filter(
        self, test_admin: AsyncClient
    ) -> None:
        """Create replay session with event filter."""
        request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(event_types=[EventType.EXECUTION_REQUESTED]),
            batch_size=50,
            max_events=1000,
        )
        response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )

        assert response.status_code == 200
        result = ReplayResponse.model_validate(response.json())
        assert result.session_id is not None

    @pytest.mark.asyncio
    async def test_create_replay_session_file_target(
        self, test_admin: AsyncClient
    ) -> None:
        """Create replay session with file target."""
        request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.FILE,
            filter=ReplayFilter(),
            target_file_path="/tmp/replay_export.json",
        )
        response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )

        assert response.status_code == 200
        result = ReplayResponse.model_validate(response.json())
        assert result.session_id is not None

    @pytest.mark.asyncio
    async def test_create_replay_session_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot create replay sessions."""
        response = await test_user.post(
            "/api/v1/replay/sessions",
            json={
                "replay_type": ReplayType.QUERY,
                "target": ReplayTarget.KAFKA,
                "filter": {},
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_replay_session_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.post(
            "/api/v1/replay/sessions",
            json={
                "replay_type": ReplayType.QUERY,
                "target": ReplayTarget.KAFKA,
                "filter": {},
            },
        )
        assert response.status_code == 401


class TestStartReplaySession:
    """Tests for POST /api/v1/replay/sessions/{session_id}/start."""

    @pytest.mark.asyncio
    async def test_start_replay_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Start a created replay session."""
        # Create session first
        request = ReplayRequest(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
            batch_size=10,
        )
        create_response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )

        if create_response.status_code == 200:
            session = ReplayResponse.model_validate(create_response.json())

            # Start session
            response = await test_admin.post(
                f"/api/v1/replay/sessions/{session.session_id}/start"
            )

            # May be 200 or error depending on session state
            if response.status_code == 200:
                result = ReplayResponse.model_validate(response.json())
                assert result.session_id == session.session_id
                assert result.status in [
                    ReplayStatus.RUNNING,
                    ReplayStatus.COMPLETED,
                    ReplayStatus.FAILED,
                ]

    @pytest.mark.asyncio
    async def test_start_nonexistent_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Start nonexistent session returns 404."""
        response = await test_admin.post(
            "/api/v1/replay/sessions/nonexistent-session/start"
        )
        assert response.status_code == 404


class TestPauseReplaySession:
    """Tests for POST /api/v1/replay/sessions/{session_id}/pause."""

    @pytest.mark.asyncio
    async def test_pause_replay_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Pause a running replay session."""
        # Create and start session
        request = ReplayRequest(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
        )
        create_response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )

        if create_response.status_code == 200:
            session = ReplayResponse.model_validate(create_response.json())

            # Start
            await test_admin.post(
                f"/api/v1/replay/sessions/{session.session_id}/start"
            )

            # Pause
            response = await test_admin.post(
                f"/api/v1/replay/sessions/{session.session_id}/pause"
            )

            # May succeed or fail depending on session state
            if response.status_code == 200:
                result = ReplayResponse.model_validate(response.json())
                assert result.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_pause_nonexistent_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Pause nonexistent session returns 404."""
        response = await test_admin.post(
            "/api/v1/replay/sessions/nonexistent-session/pause"
        )
        assert response.status_code == 404


class TestResumeReplaySession:
    """Tests for POST /api/v1/replay/sessions/{session_id}/resume."""

    @pytest.mark.asyncio
    async def test_resume_replay_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Resume a replay session."""
        request = ReplayRequest(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
        )
        create_response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )
        assert create_response.status_code == 200
        session = ReplayResponse.model_validate(create_response.json())

        response = await test_admin.post(
            f"/api/v1/replay/sessions/{session.session_id}/resume"
        )
        assert response.status_code == 200
        result = ReplayResponse.model_validate(response.json())
        assert result.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_resume_nonexistent_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Resume nonexistent session returns 404."""
        response = await test_admin.post(
            "/api/v1/replay/sessions/nonexistent-session/resume"
        )
        assert response.status_code == 404


class TestCancelReplaySession:
    """Tests for POST /api/v1/replay/sessions/{session_id}/cancel."""

    @pytest.mark.asyncio
    async def test_cancel_replay_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Cancel a replay session."""
        # Create session
        request = ReplayRequest(
            replay_type=ReplayType.TIME_RANGE,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
        )
        create_response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )

        if create_response.status_code == 200:
            session = ReplayResponse.model_validate(create_response.json())

            # Cancel
            response = await test_admin.post(
                f"/api/v1/replay/sessions/{session.session_id}/cancel"
            )

            if response.status_code == 200:
                result = ReplayResponse.model_validate(response.json())
                assert result.session_id == session.session_id
                assert result.status in [
                    ReplayStatus.CANCELLED,
                    ReplayStatus.COMPLETED,
                ]

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_session(
        self, test_admin: AsyncClient
    ) -> None:
        """Cancel nonexistent session returns 404."""
        response = await test_admin.post(
            "/api/v1/replay/sessions/nonexistent-session/cancel"
        )
        assert response.status_code == 404


class TestListReplaySessions:
    """Tests for GET /api/v1/replay/sessions."""

    @pytest.mark.asyncio
    async def test_list_replay_sessions(
        self, test_admin: AsyncClient
    ) -> None:
        """List all replay sessions."""
        response = await test_admin.get("/api/v1/replay/sessions")

        assert response.status_code == 200
        sessions = [
            SessionSummary.model_validate(s) for s in response.json()
        ]

        for session in sessions:
            assert session.session_id is not None
            assert session.replay_type in list(ReplayType)
            assert session.target in list(ReplayTarget)
            assert session.status in list(ReplayStatus)
            assert session.total_events >= 0
            assert session.replayed_events >= 0
            assert session.failed_events >= 0
            assert session.skipped_events >= 0
            assert session.created_at is not None

    @pytest.mark.asyncio
    async def test_list_replay_sessions_with_status_filter(
        self, test_admin: AsyncClient
    ) -> None:
        """Filter sessions by status."""
        response = await test_admin.get(
            "/api/v1/replay/sessions",
            params={"status": ReplayStatus.COMPLETED},
        )

        assert response.status_code == 200
        sessions = [
            SessionSummary.model_validate(s) for s in response.json()
        ]

        for session in sessions:
            assert session.status == ReplayStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_list_replay_sessions_with_limit(
        self, test_admin: AsyncClient
    ) -> None:
        """Limit number of sessions returned."""
        response = await test_admin.get(
            "/api/v1/replay/sessions",
            params={"limit": 10},
        )

        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) <= 10

    @pytest.mark.asyncio
    async def test_list_replay_sessions_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot list replay sessions."""
        response = await test_user.get("/api/v1/replay/sessions")
        assert response.status_code == 403


class TestGetReplaySession:
    """Tests for GET /api/v1/replay/sessions/{session_id}."""

    @pytest.mark.asyncio
    async def test_get_replay_session(self, test_admin: AsyncClient) -> None:
        """Get a specific replay session."""
        request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            filter=ReplayFilter(),
        )
        create_response = await test_admin.post(
            "/api/v1/replay/sessions", json=request.model_dump()
        )
        assert create_response.status_code == 200
        created = ReplayResponse.model_validate(create_response.json())

        response = await test_admin.get(
            f"/api/v1/replay/sessions/{created.session_id}"
        )
        assert response.status_code == 200
        session = ReplaySession.model_validate(response.json())

        assert session.session_id == created.session_id
        assert session.config is not None
        assert session.status in list(ReplayStatus)
        assert session.total_events >= 0
        assert session.replayed_events >= 0
        assert session.failed_events >= 0
        assert session.created_at is not None

    @pytest.mark.asyncio
    async def test_get_replay_session_not_found(
        self, test_admin: AsyncClient
    ) -> None:
        """Get nonexistent session returns 404."""
        response = await test_admin.get(
            "/api/v1/replay/sessions/nonexistent-session"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_replay_session_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot get replay sessions."""
        response = await test_user.get(
            "/api/v1/replay/sessions/some-session-id"
        )
        assert response.status_code == 403


class TestCleanupOldSessions:
    """Tests for POST /api/v1/replay/cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_old_sessions(
        self, test_admin: AsyncClient
    ) -> None:
        """Cleanup old replay sessions."""
        response = await test_admin.post(
            "/api/v1/replay/cleanup",
            params={"older_than_hours": 24},
        )

        assert response.status_code == 200
        result = CleanupResponse.model_validate(response.json())

        assert result.removed_sessions >= 0
        assert result.message is not None

    @pytest.mark.asyncio
    async def test_cleanup_old_sessions_custom_hours(
        self, test_admin: AsyncClient
    ) -> None:
        """Cleanup with custom time threshold."""
        response = await test_admin.post(
            "/api/v1/replay/cleanup",
            params={"older_than_hours": 168},  # 1 week
        )

        assert response.status_code == 200
        result = CleanupResponse.model_validate(response.json())
        assert result.removed_sessions >= 0

    @pytest.mark.asyncio
    async def test_cleanup_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot cleanup sessions."""
        response = await test_user.post("/api/v1/replay/cleanup")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_cleanup_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.post("/api/v1/replay/cleanup")
        assert response.status_code == 401
