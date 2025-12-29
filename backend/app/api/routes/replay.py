from dataclasses import asdict

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import admin_user
from app.domain.enums.replay import ReplayStatus
from app.domain.replay import ReplayConfig, ReplaySessionState
from app.schemas_pydantic.replay import (
    CleanupResponse,
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
)
from app.schemas_pydantic.replay_models import ReplaySession
from app.services.replay_service import ReplayService


def _session_to_summary(state: ReplaySessionState) -> SessionSummary:
    """Convert ReplaySessionState to SessionSummary."""
    state_data = asdict(state)
    state_data.update(state_data.pop("config"))  # flatten config fields

    duration = None
    throughput = None
    if state.started_at and state.completed_at:
        duration = (state.completed_at - state.started_at).total_seconds()
        if state.replayed_events > 0 and duration > 0:
            throughput = state.replayed_events / duration

    return SessionSummary(**state_data, duration_seconds=duration, throughput_events_per_second=throughput)


router = APIRouter(prefix="/replay", tags=["Event Replay"], route_class=DishkaRoute, dependencies=[Depends(admin_user)])


@router.post("/sessions", response_model=ReplayResponse)
async def create_replay_session(
    replay_request: ReplayRequest,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    result = await service.create_session_from_config(ReplayConfig(**replay_request.model_dump()))
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
