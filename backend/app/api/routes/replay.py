from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import admin_user
from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus
from app.domain.replay import ReplayConfig, ReplayFilter, ReplaySessionState
from app.schemas_pydantic.replay import (
    CleanupResponse,
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
)
from app.schemas_pydantic.replay_models import ReplaySession
from app.services.replay_service import ReplayService

# Fields from ReplayRequest that map to ReplayFilter
_FILTER_FIELDS = {
    "execution_id",
    "event_types",
    "start_time",
    "end_time",
    "user_id",
    "service_name",
    "custom_query",
    "exclude_event_types",
}


def _request_to_config(req: ReplayRequest) -> ReplayConfig:
    """Convert ReplayRequest to ReplayConfig."""
    filter_data = req.model_dump(include=_FILTER_FIELDS)
    target_topics = {EventType(k): v for k, v in req.target_topics.items()} if req.target_topics else None

    return ReplayConfig(
        replay_type=req.replay_type,
        target=req.target,
        filter=ReplayFilter(**filter_data),
        speed_multiplier=req.speed_multiplier,
        preserve_timestamps=req.preserve_timestamps,
        batch_size=req.batch_size,
        max_events=req.max_events,
        skip_errors=req.skip_errors,
        target_file_path=req.target_file_path,
        target_topics=target_topics,
        retry_failed=req.retry_failed,
        retry_attempts=req.retry_attempts,
        enable_progress_tracking=req.enable_progress_tracking,
    )


def _session_to_summary(state: ReplaySessionState) -> SessionSummary:
    """Convert ReplaySessionState to SessionSummary."""
    duration = None
    throughput = None
    if state.started_at and state.completed_at:
        d = (state.completed_at - state.started_at).total_seconds()
        duration = d
        if state.replayed_events > 0 and d > 0:
            throughput = state.replayed_events / d

    return SessionSummary(
        session_id=state.session_id,
        replay_type=state.config.replay_type,
        target=state.config.target,
        status=state.status,
        total_events=state.total_events,
        replayed_events=state.replayed_events,
        failed_events=state.failed_events,
        skipped_events=state.skipped_events,
        created_at=state.created_at,
        started_at=state.started_at,
        completed_at=state.completed_at,
        duration_seconds=duration,
        throughput_events_per_second=throughput,
    )


router = APIRouter(prefix="/replay", tags=["Event Replay"], route_class=DishkaRoute, dependencies=[Depends(admin_user)])


@router.post("/sessions", response_model=ReplayResponse)
async def create_replay_session(
    replay_request: ReplayRequest,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    cfg = _request_to_config(replay_request)
    result = await service.create_session_from_config(cfg)
    return ReplayResponse(session_id=result.session_id, status=result.status, message=result.message)


@router.post("/sessions/{session_id}/start", response_model=ReplayResponse)
async def start_replay_session(
    session_id: str,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    result = await service.start_session(session_id)
    return ReplayResponse(session_id=result.session_id, status=result.status, message=result.message)


@router.post("/sessions/{session_id}/pause", response_model=ReplayResponse)
async def pause_replay_session(
    session_id: str,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    result = await service.pause_session(session_id)
    return ReplayResponse(session_id=result.session_id, status=result.status, message=result.message)


@router.post("/sessions/{session_id}/resume", response_model=ReplayResponse)
async def resume_replay_session(session_id: str, service: FromDishka[ReplayService]) -> ReplayResponse:
    result = await service.resume_session(session_id)
    return ReplayResponse(session_id=result.session_id, status=result.status, message=result.message)


@router.post("/sessions/{session_id}/cancel", response_model=ReplayResponse)
async def cancel_replay_session(session_id: str, service: FromDishka[ReplayService]) -> ReplayResponse:
    result = await service.cancel_session(session_id)
    return ReplayResponse(session_id=result.session_id, status=result.status, message=result.message)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_replay_sessions(
    service: FromDishka[ReplayService],
    status: ReplayStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[SessionSummary]:
    states = service.list_sessions(status=status, limit=limit)
    return [_session_to_summary(s) for s in states]


@router.get("/sessions/{session_id}", response_model=ReplaySession)
async def get_replay_session(session_id: str, service: FromDishka[ReplayService]) -> ReplaySession:
    state = service.get_session(session_id)
    return ReplaySession.model_validate(state)


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_old_sessions(
    service: FromDishka[ReplayService],
    older_than_hours: int = Query(24, ge=1),
) -> CleanupResponse:
    result = await service.cleanup_old_sessions(older_than_hours)
    return CleanupResponse(removed_sessions=result.removed_sessions, message=result.message)
