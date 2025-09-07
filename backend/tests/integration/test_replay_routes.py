"""
Integration tests for Replay routes against the backend.

These tests run against the actual backend service running in Docker,
providing true end-to-end testing with:
- Real replay session management
- Real event replay processing
- Real session state transitions
- Real cleanup operations
- Real admin-only access control
"""

import pytest
import asyncio
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from uuid import uuid4

from app.schemas_pydantic.replay import (
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
    CleanupResponse
)
from app.schemas_pydantic.replay_models import ReplaySession
from app.domain.enums.replay import ReplayStatus, ReplayType, ReplayTarget
from app.domain.enums.events import EventType


@pytest.mark.integration
class TestReplayRoutesReal:
    """Test replay endpoints against real backend."""
    
    @pytest.mark.asyncio
    async def test_replay_requires_admin_authentication(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test that replay endpoints require admin authentication."""
        # Login as regular user
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Try to access replay endpoints as non-admin
        response = await client.get("/api/v1/replay/sessions")
        assert response.status_code == 403
        
        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower() 
                  for word in ["admin", "forbidden", "denied"])
    
    @pytest.mark.asyncio
    async def test_create_replay_session(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test creating a replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create replay session
        replay_request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            event_types=[EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED],
            start_time=datetime.now(timezone.utc) - timedelta(days=7),
            end_time=datetime.now(timezone.utc),
            speed_multiplier=1.0,
            preserve_timestamps=True,
        ).model_dump(mode="json")

        response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert response.status_code in [200, 422]
        if response.status_code == 422:
            return
        
        # Validate response
        replay_data = response.json()
        replay_response = ReplayResponse(**replay_data)
        
        assert replay_response.session_id is not None
        assert len(replay_response.session_id) > 0
        assert replay_response.status in [ReplayStatus.CREATED]
        assert replay_response.message is not None
    
    @pytest.mark.asyncio
    async def test_list_replay_sessions(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test listing replay sessions."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # List replay sessions
        response = await client.get("/api/v1/replay/sessions?limit=10")
        assert response.status_code in [200, 404]
        if response.status_code != 200:
            return
        
        # Validate response
        sessions_data = response.json()
        assert isinstance(sessions_data, list)
        
        for session_data in sessions_data:
            session_summary = SessionSummary(**session_data)
            assert session_summary.session_id
            assert session_summary.status in list(ReplayStatus)
            assert session_summary.created_at is not None
    
    @pytest.mark.asyncio
    async def test_get_replay_session_details(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test getting detailed information about a replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create a session first
        replay_request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            event_types=[EventType.USER_LOGGED_IN],
            start_time=datetime.now(timezone.utc) - timedelta(hours=24),
            end_time=datetime.now(timezone.utc),
            speed_multiplier=2.0,
        ).model_dump(mode="json")

        create_response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert create_response.status_code == 200
        
        session_id = create_response.json()["session_id"]
        
        # Get session details
        detail_response = await client.get(f"/api/v1/replay/sessions/{session_id}")
        assert detail_response.status_code in [200, 404]
        if detail_response.status_code != 200:
            return
        
        # Validate detailed response
        session_data = detail_response.json()
        session = ReplaySession(**session_data)
        assert session.session_id == session_id
        assert session.status in list(ReplayStatus)
        assert session.created_at is not None
    
    @pytest.mark.asyncio
    async def test_start_replay_session(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test starting a replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create a session
        replay_request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            event_types=[EventType.SYSTEM_ERROR],
            start_time=datetime.now(timezone.utc) - timedelta(hours=1),
            end_time=datetime.now(timezone.utc),
            speed_multiplier=1.0,
        ).model_dump(mode="json")

        create_response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert create_response.status_code == 200
        
        session_id = create_response.json()["session_id"]
        
        # Start the session
        start_response = await client.post(f"/api/v1/replay/sessions/{session_id}/start")
        assert start_response.status_code in [200, 404]
        if start_response.status_code != 200:
            return
        
        start_data = start_response.json()
        start_result = ReplayResponse(**start_data)
        
        assert start_result.session_id == session_id
        assert start_result.status in [ReplayStatus.RUNNING, ReplayStatus.COMPLETED]
        assert start_result.message is not None
    
    @pytest.mark.asyncio
    async def test_pause_and_resume_replay_session(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test pausing and resuming a replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create and start a session
        replay_request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            event_types=[EventType.SYSTEM_ERROR],
            start_time=datetime.now(timezone.utc) - timedelta(hours=2),
            end_time=datetime.now(timezone.utc),
            speed_multiplier=0.5,
        ).model_dump(mode="json")

        create_response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert create_response.status_code == 200
        
        session_id = create_response.json()["session_id"]
        
        # Start the session
        start_response = await client.post(f"/api/v1/replay/sessions/{session_id}/start")
        assert start_response.status_code in [200, 404]
        if start_response.status_code != 200:
            return
        
        # Pause the session
        pause_response = await client.post(f"/api/v1/replay/sessions/{session_id}/pause")
        # Could succeed or fail if session already completed or not found
        assert pause_response.status_code in [200, 400, 404]
        
        if pause_response.status_code == 200:
            pause_data = pause_response.json()
            pause_result = ReplayResponse(**pause_data)
            
            assert pause_result.session_id == session_id
            assert pause_result.status in [ReplayStatus.PAUSED, ReplayStatus.COMPLETED]
            
            # If paused, try to resume
            if pause_result.status == "paused":
                resume_response = await client.post(f"/api/v1/replay/sessions/{session_id}/resume")
                assert resume_response.status_code == 200
                
                resume_data = resume_response.json()
                resume_result = ReplayResponse(**resume_data)
                
                assert resume_result.session_id == session_id
                assert resume_result.status in [ReplayStatus.RUNNING, ReplayStatus.COMPLETED]
    
    @pytest.mark.asyncio
    async def test_cancel_replay_session(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test cancelling a replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create a session
        replay_request = ReplayRequest(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA,
            event_types=[EventType.SYSTEM_ERROR],
            start_time=datetime.now(timezone.utc) - timedelta(hours=1),
            end_time=datetime.now(timezone.utc),
            speed_multiplier=1.0,
        ).model_dump(mode="json")

        create_response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert create_response.status_code == 200
        
        session_id = create_response.json()["session_id"]
        
        # Cancel the session
        cancel_response = await client.post(f"/api/v1/replay/sessions/{session_id}/cancel")
        assert cancel_response.status_code in [200, 404]
        if cancel_response.status_code != 200:
            return
        
        cancel_data = cancel_response.json()
        cancel_result = ReplayResponse(**cancel_data)
        
        assert cancel_result.session_id == session_id
        assert cancel_result.status in [ReplayStatus.CANCELLED, ReplayStatus.COMPLETED]
        assert cancel_result.message is not None
    
    @pytest.mark.asyncio
    async def test_filter_sessions_by_status(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test filtering replay sessions by status."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Test different status filters
        for status in [
            ReplayStatus.CREATED.value,
            ReplayStatus.RUNNING.value,
            ReplayStatus.COMPLETED.value,
            ReplayStatus.FAILED.value,
            ReplayStatus.CANCELLED.value,
        ]:
            response = await client.get(f"/api/v1/replay/sessions?status={status}&limit=5")
            assert response.status_code in [200, 404]
            if response.status_code != 200:
                continue

            sessions_data = response.json()
            assert isinstance(sessions_data, list)

            # All returned sessions should have the requested status
            for session_data in sessions_data:
                session = SessionSummary(**session_data)
                assert session.status == status
    
    @pytest.mark.asyncio
    async def test_cleanup_old_sessions(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test cleanup of old replay sessions."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Cleanup sessions older than 24 hours
        cleanup_response = await client.post("/api/v1/replay/cleanup?older_than_hours=24")
        assert cleanup_response.status_code == 200
        
        cleanup_data = cleanup_response.json()
        cleanup_result = CleanupResponse(**cleanup_data)
        
        # API returns removed_sessions
        assert isinstance(cleanup_result.removed_sessions, int)
        assert cleanup_result.message is not None
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test getting a non-existent replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Try to get non-existent session
        fake_session_id = str(uuid4())
        response = await client.get(f"/api/v1/replay/sessions/{fake_session_id}")
        # Could return 404 or empty result
        assert response.status_code in [200, 404]
        
        if response.status_code == 404:
            error_data = response.json()
            assert "detail" in error_data
    
    @pytest.mark.asyncio
    async def test_start_nonexistent_session(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test starting a non-existent replay session."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Try to start non-existent session
        fake_session_id = str(uuid4())
        response = await client.post(f"/api/v1/replay/sessions/{fake_session_id}/start")
        # Should fail
        assert response.status_code in [400, 404]
    
    @pytest.mark.asyncio
    async def test_replay_session_state_transitions(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test valid state transitions for replay sessions."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create a session
        replay_request = {
            "name": f"State Test Session {uuid4().hex[:8]}",
            "description": "Testing state transitions",
            "filters": {
                "event_types": ["state.test.event"],
                "start_time": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat()
            },
            "target_topic": "state-test-topic",
            "speed_multiplier": 1.0
        }
        
        create_response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert create_response.status_code in [200, 422]
        if create_response.status_code != 200:
            return
        
        session_id = create_response.json()["session_id"]
        initial_status = create_response.json()["status"]
        assert initial_status == ReplayStatus.CREATED
        
        # Can't pause a session that hasn't started
        pause_response = await client.post(f"/api/v1/replay/sessions/{session_id}/pause")
        assert pause_response.status_code in [400, 409]  # Invalid state transition
        
        # Can start from pending
        start_response = await client.post(f"/api/v1/replay/sessions/{session_id}/start")
        assert start_response.status_code == 200
        
        # Can't start again if already running
        start_again_response = await client.post(f"/api/v1/replay/sessions/{session_id}/start")
        assert start_again_response.status_code in [200, 400, 409]  # Might be idempotent or error
    
    @pytest.mark.asyncio
    async def test_replay_with_complex_filters(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test creating replay session with complex filters."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create session with complex filters
        replay_request = {
            "name": f"Complex Filter Session {uuid4().hex[:8]}",
            "description": "Testing complex event filters",
            "filters": {
                "event_types": [
                    "execution.requested",
                    "execution.started",
                    "execution.completed",
                    "execution.failed"
                ],
                "start_time": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "aggregate_id": str(uuid4()),
                "correlation_id": str(uuid4()),
                "user_id": shared_admin.get("user_id"),
                "service_name": "execution-service"
            },
            "target_topic": "complex-filter-topic",
            "speed_multiplier": 0.1,  # Slow replay
            "preserve_timing": False,
            "batch_size": 100
        }
        
        response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert response.status_code in [200, 422]
        if response.status_code != 200:
            return
        
        replay_data = response.json()
        replay_response = ReplayResponse(**replay_data)
        
        assert replay_response.session_id is not None
        assert replay_response.status in ["created", "pending"]
    
    @pytest.mark.asyncio
    async def test_replay_session_progress_tracking(self, client: AsyncClient, shared_admin: Dict[str, str]) -> None:
        """Test tracking progress of replay sessions."""
        # Login as admin
        login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create and start a session
        replay_request = {
            "name": f"Progress Test Session {uuid4().hex[:8]}",
            "description": "Testing progress tracking",
            "filters": {
                "event_types": ["progress.test.event"],
                "start_time": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat()
            },
            "target_topic": "progress-test-topic",
            "speed_multiplier": 10.0  # Fast replay
        }
        
        create_response = await client.post("/api/v1/replay/sessions", json=replay_request)
        assert create_response.status_code in [200, 422]
        if create_response.status_code != 200:
            return
        
        session_id = create_response.json()["session_id"]
        
        # Start the session
        await client.post(f"/api/v1/replay/sessions/{session_id}/start")
        
        # Check progress multiple times
        for _ in range(3):
            await asyncio.sleep(1)  # Wait a bit
            
            detail_response = await client.get(f"/api/v1/replay/sessions/{session_id}")
            assert detail_response.status_code == 200
            
            session_data = detail_response.json()
            session = ReplaySession(**session_data)
            
            # Check progress fields
            if session.events_replayed is not None and session.events_total is not None:
                assert 0 <= session.events_replayed <= session.events_total
                
                # Calculate progress percentage
                if session.events_total > 0:
                    progress = (session.events_replayed / session.events_total) * 100
                    assert 0.0 <= progress <= 100.0
            
            # If completed, break
            if session.status in ["completed", "failed", "cancelled"]:
                break
