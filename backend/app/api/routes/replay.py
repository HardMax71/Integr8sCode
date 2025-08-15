from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_admin
from app.core.service_dependencies import ReplayRepositoryDep
from app.schemas_pydantic.replay import (
    CleanupResponse,
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
)
from app.services.event_replay import ReplaySession, ReplayStatus

router = APIRouter(prefix="/replay", tags=["Event Replay"])


@router.post("/sessions", response_model=ReplayResponse)
async def create_replay_session(
        request: ReplayRequest,
        repository: ReplayRepositoryDep,
        current_user: dict = Depends(require_admin),
) -> ReplayResponse:
    """Create a new replay session"""
    return await repository.create_session(
        replay_type=request.replay_type,
        target=request.target,
        execution_id=request.execution_id,
        event_types=request.event_types,
        start_time=request.start_time,
        end_time=request.end_time,
        user_id=request.user_id,
        service_name=request.service_name,
        speed_multiplier=request.speed_multiplier,
        preserve_timestamps=request.preserve_timestamps,
        batch_size=request.batch_size,
        max_events=request.max_events,
        skip_errors=request.skip_errors,
        target_file_path=request.target_file_path,
        current_user=current_user
    )


@router.post("/sessions/{session_id}/start", response_model=ReplayResponse)
async def start_replay_session(
        session_id: str,
        repository: ReplayRepositoryDep,
        current_user: dict = Depends(require_admin)
) -> ReplayResponse:
    """Start a replay session"""
    return await repository.start_session(session_id)


@router.post("/sessions/{session_id}/pause", response_model=ReplayResponse)
async def pause_replay_session(
        session_id: str,
        repository: ReplayRepositoryDep,
        current_user: dict = Depends(require_admin)
) -> ReplayResponse:
    """Pause a running replay session"""
    return await repository.pause_session(session_id)


@router.post("/sessions/{session_id}/resume", response_model=ReplayResponse)
async def resume_replay_session(
        session_id: str,
        repository: ReplayRepositoryDep,
        current_user: dict = Depends(require_admin)
) -> ReplayResponse:
    """Resume a paused replay session"""
    return await repository.resume_session(session_id)


@router.post("/sessions/{session_id}/cancel", response_model=ReplayResponse)
async def cancel_replay_session(
        session_id: str,
        repository: ReplayRepositoryDep,
        current_user: dict = Depends(require_admin)
) -> ReplayResponse:
    """Cancel a replay session"""
    return await repository.cancel_session(session_id)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_replay_sessions(
        repository: ReplayRepositoryDep,
        status: Optional[ReplayStatus] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        current_user: dict = Depends(require_admin)
) -> list[SessionSummary]:
    """list replay sessions with optional filtering"""
    return repository.list_sessions(status=status, limit=limit)


@router.get("/sessions/{session_id}", response_model=ReplaySession)
async def get_replay_session(
        session_id: str,
        repository: ReplayRepositoryDep,
        current_user: dict = Depends(require_admin)
) -> ReplaySession:
    """Get details of a specific replay session"""
    return repository.get_session(session_id)


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_old_sessions(
        repository: ReplayRepositoryDep,
        older_than_hours: int = Query(24, ge=1),
        current_user: dict = Depends(require_admin)
) -> CleanupResponse:
    """Clean up old replay sessions"""
    return await repository.cleanup_old_sessions(older_than_hours)
