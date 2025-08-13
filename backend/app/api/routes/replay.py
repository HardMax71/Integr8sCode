from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_admin
from app.db.repositories.replay_repository import ReplayRepository, get_replay_repository
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
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
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
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> ReplayResponse:
    """Start a replay session"""
    return await repository.start_session(session_id)


@router.post("/sessions/{session_id}/pause", response_model=ReplayResponse)
async def pause_replay_session(
        session_id: str,
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> ReplayResponse:
    """Pause a running replay session"""
    return await repository.pause_session(session_id)


@router.post("/sessions/{session_id}/resume", response_model=ReplayResponse)
async def resume_replay_session(
        session_id: str,
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> ReplayResponse:
    """Resume a paused replay session"""
    return await repository.resume_session(session_id)


@router.post("/sessions/{session_id}/cancel", response_model=ReplayResponse)
async def cancel_replay_session(
        session_id: str,
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> ReplayResponse:
    """Cancel a replay session"""
    return await repository.cancel_session(session_id)


@router.get("/sessions", response_model=List[SessionSummary])
async def list_replay_sessions(
        status: Optional[ReplayStatus] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> List[SessionSummary]:
    """List replay sessions with optional filtering"""
    return repository.list_sessions(status=status, limit=limit)


@router.get("/sessions/{session_id}", response_model=ReplaySession)
async def get_replay_session(
        session_id: str,
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> ReplaySession:
    """Get details of a specific replay session"""
    return repository.get_session(session_id)


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_old_sessions(
        older_than_hours: int = Query(24, ge=1),
        current_user: dict = Depends(require_admin),
        repository: ReplayRepository = Depends(get_replay_repository)
) -> CleanupResponse:
    """Clean up old replay sessions"""
    return await repository.cleanup_old_sessions(older_than_hours)
