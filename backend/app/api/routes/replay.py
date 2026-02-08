from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query

from app.api.dependencies import admin_user
from app.domain.enums import ReplayStatus
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
    """Create a new event replay session from a configuration."""
    result = await service.create_session_from_config(ReplayConfig(**replay_request.model_dump()))
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/start", response_model=ReplayResponse)
async def start_replay_session(
    session_id: str,
    service: FromDishka[EventReplayService],
) -> ReplayResponse:
    """Start a previously created replay session."""
    result = await service.start_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/pause", response_model=ReplayResponse)
async def pause_replay_session(
    session_id: str,
    service: FromDishka[EventReplayService],
) -> ReplayResponse:
    """Pause a running replay session."""
    result = await service.pause_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/resume", response_model=ReplayResponse)
async def resume_replay_session(session_id: str, service: FromDishka[EventReplayService]) -> ReplayResponse:
    """Resume a paused replay session."""
    result = await service.resume_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.post("/sessions/{session_id}/cancel", response_model=ReplayResponse)
async def cancel_replay_session(session_id: str, service: FromDishka[EventReplayService]) -> ReplayResponse:
    """Cancel and stop a replay session."""
    result = await service.cancel_session(session_id)
    return ReplayResponse(**result.model_dump())


@router.get("/sessions", response_model=list[SessionSummary])
async def list_replay_sessions(
    service: FromDishka[EventReplayService],
    status: Annotated[ReplayStatus | None, Query(description="Filter by replay session status")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[SessionSummary]:
    """List replay sessions with optional status filtering."""
    return [
        SessionSummary(**{**s.model_dump(), **s.config.model_dump()})
        for s in service.list_sessions(status=status, limit=limit)
    ]


@router.get("/sessions/{session_id}", response_model=ReplaySession)
async def get_replay_session(session_id: str, service: FromDishka[EventReplayService]) -> ReplaySession:
    """Get full details of a replay session."""
    return ReplaySession.model_validate(service.get_session(session_id))


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_old_sessions(
    service: FromDishka[EventReplayService],
    older_than_hours: Annotated[int, Query(ge=1, description="Delete sessions older than this many hours")] = 24,
) -> CleanupResponse:
    """Remove replay sessions older than the specified threshold."""
    result = await service.cleanup_old_sessions(older_than_hours)
    return CleanupResponse(**result.model_dump())
