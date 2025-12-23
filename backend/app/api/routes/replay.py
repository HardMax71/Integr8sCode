from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import admin_user
from app.domain.enums.replay import ReplayStatus
from app.infrastructure.mappers import ReplayApiMapper
from app.schemas_pydantic.replay import (
    CleanupResponse,
    ReplayRequest,
    ReplayResponse,
    SessionSummary,
)
from app.schemas_pydantic.replay_models import ReplaySession
from app.services.replay_service import ReplayService

router = APIRouter(prefix="/replay", tags=["Event Replay"], route_class=DishkaRoute, dependencies=[Depends(admin_user)])


@router.post("/sessions", response_model=ReplayResponse)
async def create_replay_session(
    replay_request: ReplayRequest,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    cfg = ReplayApiMapper.request_to_config(replay_request)
    result = await service.create_session_from_config(cfg)
    return ReplayApiMapper.op_to_response(result.session_id, result.status, result.message)


@router.post("/sessions/{session_id}/start", response_model=ReplayResponse)
async def start_replay_session(
    session_id: str,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    result = await service.start_session(session_id)
    return ReplayApiMapper.op_to_response(result.session_id, result.status, result.message)


@router.post("/sessions/{session_id}/pause", response_model=ReplayResponse)
async def pause_replay_session(
    session_id: str,
    service: FromDishka[ReplayService],
) -> ReplayResponse:
    result = await service.pause_session(session_id)
    return ReplayApiMapper.op_to_response(result.session_id, result.status, result.message)


@router.post("/sessions/{session_id}/resume", response_model=ReplayResponse)
async def resume_replay_session(session_id: str, service: FromDishka[ReplayService]) -> ReplayResponse:
    result = await service.resume_session(session_id)
    return ReplayApiMapper.op_to_response(result.session_id, result.status, result.message)


@router.post("/sessions/{session_id}/cancel", response_model=ReplayResponse)
async def cancel_replay_session(session_id: str, service: FromDishka[ReplayService]) -> ReplayResponse:
    result = await service.cancel_session(session_id)
    return ReplayApiMapper.op_to_response(result.session_id, result.status, result.message)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_replay_sessions(
    service: FromDishka[ReplayService],
    status: ReplayStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[SessionSummary]:
    states = service.list_sessions(status=status, limit=limit)
    return [ReplayApiMapper.session_to_summary(s) for s in states]


@router.get("/sessions/{session_id}", response_model=ReplaySession)
async def get_replay_session(session_id: str, service: FromDishka[ReplayService]) -> ReplaySession:
    state = service.get_session(session_id)
    return ReplayApiMapper.session_to_response(state)


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_old_sessions(
    service: FromDishka[ReplayService],
    older_than_hours: int = Query(24, ge=1),
) -> CleanupResponse:
    result = await service.cleanup_old_sessions(older_than_hours)
    return ReplayApiMapper.cleanup_to_response(result.removed_sessions, result.message)
