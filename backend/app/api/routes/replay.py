from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import admin_user
from app.domain.enums.replay import ReplayStatus
from app.domain.replay import ReplayConfig
from app.schemas_pydantic.replay import (
    CleanupResponse,
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
)
from app.schemas_pydantic.replay_models import ReplaySession
from app.services.event_replay import EventReplayService

router = APIRouter(prefix="/replay", tags=["Event Replay"], route_class=DishkaRoute, dependencies=[Depends(admin_user)])


@router.post("/sessions", response_model=ReplayResponse)
async def create_replay_session(
    replay_request: ReplayRequest,
    service: FromDishka[EventReplayService],
) -> ReplayResponse:
    result = await service.create_session_from_config(ReplayConfig(**replay_request.model_dump()))
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/start", response_model=ReplayResponse)
async def start_replay_session(
    session_id: str,
    service: FromDishka[EventReplayService],
) -> ReplayResponse:
    result = await service.start_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/pause", response_model=ReplayResponse)
async def pause_replay_session(
    session_id: str,
    service: FromDishka[EventReplayService],
) -> ReplayResponse:
    result = await service.pause_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/resume", response_model=ReplayResponse)
async def resume_replay_session(session_id: str, service: FromDishka[EventReplayService]) -> ReplayResponse:
    result = await service.resume_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/cancel", response_model=ReplayResponse)
async def cancel_replay_session(session_id: str, service: FromDishka[EventReplayService]) -> ReplayResponse:
    result = await service.cancel_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.get("/sessions", response_model=list[SessionSummary])
async def list_replay_sessions(
    service: FromDishka[EventReplayService],
    status: ReplayStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[SessionSummary]:
    return [
        SessionSummary(**{**s.model_dump(), **s.config.model_dump()})
        for s in service.list_sessions(status=status, limit=limit)
    ]


@router.get("/sessions/{session_id}", response_model=ReplaySession)
async def get_replay_session(session_id: str, service: FromDishka[EventReplayService]) -> ReplaySession:
    return ReplaySession.model_validate(service.get_session(session_id))


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_old_sessions(
    service: FromDishka[EventReplayService],
    older_than_hours: int = Query(24, ge=1),
) -> CleanupResponse:
    result = await service.cleanup_old_sessions(older_than_hours)
    return CleanupResponse(**result.model_dump())
