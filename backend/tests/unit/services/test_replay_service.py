import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.schemas_pydantic.replay import CleanupResponse, ReplayRequest
from app.schemas_pydantic.replay_models import ReplaySession
from app.services.event_replay import ReplayConfig, ReplayFilter
from app.services.replay_service import ReplayService


class FakeEventReplayService:
    def __init__(self):
        self.sessions: dict[str, ReplaySession] = {}
    async def create_replay_session(self, config: ReplayConfig) -> str:  # noqa: D401
        s = ReplaySession(config=config)
        self.sessions[s.session_id] = s
        return s.session_id
    def get_session(self, sid: str):  # noqa: D401
        return self.sessions.get(sid)
    def list_sessions(self, status=None, limit=100):  # noqa: D401
        vals = list(self.sessions.values())
        return vals[:limit]
    async def start_replay(self, sid: str):  # noqa: D401, ANN001
        if sid not in self.sessions: raise ValueError("notfound")
    async def pause_replay(self, sid: str):  # noqa: D401, ANN001
        if sid not in self.sessions: raise ValueError("notfound")
    async def resume_replay(self, sid: str):  # noqa: D401, ANN001
        if sid not in self.sessions: raise ValueError("notfound")
    async def cancel_replay(self, sid: str):  # noqa: D401, ANN001
        if sid not in self.sessions: raise ValueError("notfound")
    async def cleanup_old_sessions(self, hours: int):  # noqa: D401, ANN001
        return 1


class FakeRepo:
    async def save_session(self, session: ReplaySession): return None  # noqa: D401, ANN001
    async def update_session_status(self, session_id: str, status: ReplayStatus): return True  # noqa: D401, ANN001
    async def delete_old_sessions(self, cutoff_iso: str): return 1  # noqa: D401, ANN001


@pytest.mark.asyncio
async def test_create_start_pause_resume_cancel_and_errors() -> None:
    ers = FakeEventReplayService(); repo = FakeRepo()
    svc = ReplayService(repository=repo, event_replay_service=ers)
    # Create from request
    req = ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA, execution_id="e1")
    resp = await svc.create_session(req)
    assert resp.status == ReplayStatus.CREATED

    sid = resp.session_id
    # Start
    st = await svc.start_session(sid)
    assert st.status == ReplayStatus.RUNNING
    # Pause
    pa = await svc.pause_session(sid)
    assert pa.status == ReplayStatus.PAUSED
    # Resume
    rs = await svc.resume_session(sid)
    assert rs.status == ReplayStatus.RUNNING
    # Cancel
    ca = await svc.cancel_session(sid)
    assert ca.status == ReplayStatus.CANCELLED

    # Error paths -> 404
    with pytest.raises(Exception):
        await svc.start_session("missing")

    # create_session error path (event replay raises)
    ers_bad = FakeEventReplayService()
    async def raise_create(_cfg):  # noqa: ANN001
        raise RuntimeError("boom")
    ers_bad.create_replay_session = raise_create  # type: ignore[assignment]
    svc_bad = ReplayService(repository=repo, event_replay_service=ers_bad)
    with pytest.raises(Exception):
        await svc_bad.create_session(ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA))


def test_list_and_get_session_and_summary() -> None:
    ers = FakeEventReplayService(); repo = FakeRepo(); svc = ReplayService(repo, ers)
    # Create via config helper
    cfg = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA, filter=ReplayFilter())
    sid = asyncio.get_event_loop().run_until_complete(ers.create_replay_session(cfg))
    # list
    lst = svc.list_sessions(limit=10)
    assert len(lst) == 1 and lst[0].session_id == sid
    # get session
    s = svc.get_session(sid)
    assert s.session_id == sid
    # not found
    with pytest.raises(Exception):
        _ = svc.get_session("missing")
    # _session_to_summary throughput and duration when started/completed
    sess = ers.get_session(sid)
    sess.started_at = datetime.now(timezone.utc)
    sess.completed_at = sess.started_at + timedelta(seconds=1)
    sess.replayed_events = 1
    summary = svc._session_to_summary(sess)
    assert summary.duration_seconds is not None and summary.throughput_events_per_second is not None


@pytest.mark.asyncio
async def test_cleanup_old_sessions_happy_path() -> None:
    ers = FakeEventReplayService(); repo = FakeRepo(); svc = ReplayService(repo, ers)
    res = await svc.cleanup_old_sessions(older_than_hours=1)
    assert isinstance(res, type(CleanupResponse(removed_sessions=1, message="x")))
    # cleanup error path
    class BadRepo(FakeRepo):
        async def delete_old_sessions(self, cutoff_iso: str):  # noqa: D401, ANN001
            raise RuntimeError("x")
    svc_err = ReplayService(BadRepo(), ers)
    with pytest.raises(Exception):
        await svc_err.cleanup_old_sessions(1)


@pytest.mark.asyncio
async def test_create_session_when_get_session_returns_none() -> None:
    """Test create_session when event_replay_service.get_session returns None"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    
    # Override get_session to return None
    ers.get_session = lambda _: None
    
    svc = ReplayService(repository=repo, event_replay_service=ers)
    req = ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA, execution_id="e1")
    resp = await svc.create_session(req)
    assert resp.status == ReplayStatus.CREATED


@pytest.mark.asyncio
async def test_start_session_general_exception() -> None:
    """Test start_session handling general exceptions"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    
    async def raise_general(_):
        raise RuntimeError("General error")
    ers.start_replay = raise_general
    
    svc = ReplayService(repository=repo, event_replay_service=ers)
    
    # Create a session first
    req = ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA)
    resp = await svc.create_session(req)
    
    # Test general exception
    with pytest.raises(Exception) as exc:
        await svc.start_session(resp.session_id)
    assert "General error" in str(exc.value)


@pytest.mark.asyncio
async def test_pause_session_exceptions() -> None:
    """Test pause_session exception handling"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    svc = ReplayService(repository=repo, event_replay_service=ers)
    
    # Create a session
    req = ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA)
    resp = await svc.create_session(req)
    
    # Test ValueError (not found)
    with pytest.raises(Exception):
        await svc.pause_session("nonexistent")
    
    # Test general exception
    async def raise_general(_):
        raise RuntimeError("Pause error")
    ers.pause_replay = raise_general
    
    with pytest.raises(Exception) as exc:
        await svc.pause_session(resp.session_id)
    assert "Pause error" in str(exc.value)


@pytest.mark.asyncio
async def test_resume_session_exceptions() -> None:
    """Test resume_session exception handling"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    svc = ReplayService(repository=repo, event_replay_service=ers)
    
    # Create a session
    req = ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA)
    resp = await svc.create_session(req)
    
    # Test ValueError (not found)
    with pytest.raises(Exception):
        await svc.resume_session("nonexistent")
    
    # Test general exception
    async def raise_general(_):
        raise RuntimeError("Resume error")
    ers.resume_replay = raise_general
    
    with pytest.raises(Exception) as exc:
        await svc.resume_session(resp.session_id)
    assert "Resume error" in str(exc.value)


@pytest.mark.asyncio
async def test_cancel_session_exceptions() -> None:
    """Test cancel_session exception handling"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    svc = ReplayService(repository=repo, event_replay_service=ers)
    
    # Create a session
    req = ReplayRequest(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA)
    resp = await svc.create_session(req)
    
    # Test ValueError (not found)
    with pytest.raises(Exception):
        await svc.cancel_session("nonexistent")
    
    # Test general exception
    async def raise_general(_):
        raise RuntimeError("Cancel error")
    ers.cancel_replay = raise_general
    
    with pytest.raises(Exception) as exc:
        await svc.cancel_session(resp.session_id)
    assert "Cancel error" in str(exc.value)


def test_get_session_general_exception() -> None:
    """Test get_session handling general exceptions"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    
    def raise_general(_):
        raise RuntimeError("Get session error")
    ers.get_session = raise_general
    
    svc = ReplayService(repository=repo, event_replay_service=ers)
    
    with pytest.raises(Exception) as exc:
        svc.get_session("any_id")
    assert "Internal server error" in str(exc.value)


def test_session_to_summary_without_duration() -> None:
    """Test _session_to_summary when duration calculation not possible"""
    ers = FakeEventReplayService()
    repo = FakeRepo()
    svc = ReplayService(repository=repo, event_replay_service=ers)
    
    cfg = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA, filter=ReplayFilter())
    session = ReplaySession(config=cfg)
    
    # Without started_at and completed_at
    summary = svc._session_to_summary(session)
    assert summary.duration_seconds is None
    assert summary.throughput_events_per_second is None
    
    # With started_at but no completed_at
    session.started_at = datetime.now(timezone.utc)
    summary = svc._session_to_summary(session)
    assert summary.duration_seconds is None
    assert summary.throughput_events_per_second is None
    
    # With zero duration (edge case)
    session.completed_at = session.started_at
    session.replayed_events = 10
    summary = svc._session_to_summary(session)
    assert summary.duration_seconds == 0
    assert summary.throughput_events_per_second is None  # Can't divide by zero
