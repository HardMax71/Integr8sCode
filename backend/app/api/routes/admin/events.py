from datetime import datetime
from typing import Annotated
from uuid import uuid4

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter

from app.api.dependencies import admin_user
from app.domain.enums import EventType, ExportFormat
from app.domain.events import EventFilter as DomainEventFilter
from app.domain.replay import ReplayFilter
from app.domain.user import User
from app.schemas_pydantic.admin_events import (
    EventBrowseRequest,
    EventBrowseResponse,
    EventDeleteResponse,
    EventDetailResponse,
    EventReplayRequest,
    EventReplayResponse,
    EventReplayStatusResponse,
    EventStatsResponse,
)
from app.schemas_pydantic.common import ErrorResponse
from app.services.admin import AdminEventsService

_domain_filter_ta = TypeAdapter(DomainEventFilter)

router = APIRouter(
    prefix="/admin/events", tags=["admin-events"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.post("/browse")
async def browse_events(request: EventBrowseRequest, service: FromDishka[AdminEventsService]) -> EventBrowseResponse:
    """Browse events with filtering, sorting, and pagination."""
    result = await service.browse_events(
        event_filter=_domain_filter_ta.validate_python(request.filters.model_dump()),
        skip=request.skip,
        limit=request.limit,
    )

    return EventBrowseResponse.model_validate(result)


@router.get("/stats")
async def get_event_stats(
    service: FromDishka[AdminEventsService],
    hours: Annotated[int, Query(ge=1, le=168, description="Lookback window in hours (max 168)")] = 24,
) -> EventStatsResponse:
    """Get event statistics for a given lookback window."""
    stats = await service.get_event_stats(hours=hours)
    return EventStatsResponse.model_validate(stats)


@router.get("/export/{export_format}")
async def export_events(
    export_format: ExportFormat,
    service: FromDishka[AdminEventsService],
    event_types: Annotated[list[EventType] | None, Query(description="Event types (repeat param for multiple)")] = None,
    aggregate_id: Annotated[str | None, Query(description="Aggregate ID filter")] = None,
    user_id: Annotated[str | None, Query(description="User ID filter")] = None,
    service_name: Annotated[str | None, Query(description="Service name filter")] = None,
    start_time: Annotated[datetime | None, Query(description="Start time")] = None,
    end_time: Annotated[datetime | None, Query(description="End time")] = None,
    limit: Annotated[int, Query(ge=1, le=50000)] = 10000,
) -> StreamingResponse:
    """Export filtered events as a downloadable file."""
    export_filter = DomainEventFilter(
        event_types=event_types,
        aggregate_id=aggregate_id,
        user_id=user_id,
        service_name=service_name,
        start_time=start_time,
        end_time=end_time,
    )
    result = await service.export_events(event_filter=export_filter, limit=limit, export_format=export_format)
    return StreamingResponse(
        iter([result.content]),
        media_type=result.media_type,
        headers={"Content-Disposition": f"attachment; filename={result.file_name}"},
    )


@router.get("/{event_id}", responses={404: {"model": ErrorResponse, "description": "Event not found"}})
async def get_event_detail(event_id: str, service: FromDishka[AdminEventsService]) -> EventDetailResponse:
    """Get detailed information about a single event, including related events and timeline."""
    result = await service.get_event_detail(event_id)

    if not result:
        raise HTTPException(status_code=404, detail="Event not found")

    return EventDetailResponse.model_validate(result)


@router.post(
    "/replay",
    responses={
        404: {"model": ErrorResponse, "description": "No events match the replay filter"},
        422: {"model": ErrorResponse, "description": "Empty filter or too many events to replay"},
    },
)
async def replay_events(
    request: EventReplayRequest, background_tasks: BackgroundTasks, service: FromDishka[AdminEventsService]
) -> EventReplayResponse:
    """Replay events by filter criteria, with optional dry-run mode."""
    replay_id = f"replay-{uuid4().hex}"
    result = await service.prepare_or_schedule_replay(
        replay_filter=ReplayFilter.model_validate(request),
        dry_run=request.dry_run,
        replay_id=replay_id,
        target_service=request.target_service,
    )

    if not result.dry_run and result.session_id:
        background_tasks.add_task(service.start_replay_session, result.session_id)

    return EventReplayResponse.model_validate(result)


@router.get(
    "/replay/{session_id}/status",
    responses={404: {"model": ErrorResponse, "description": "Replay session not found"}},
)
async def get_replay_status(session_id: str, service: FromDishka[AdminEventsService]) -> EventReplayStatusResponse:
    """Get the status and progress of a replay session."""
    status = await service.get_replay_status(session_id)

    if not status:
        raise HTTPException(status_code=404, detail="Replay session not found")

    return EventReplayStatusResponse.model_validate(status)


@router.delete("/{event_id}", responses={404: {"model": ErrorResponse, "description": "Event not found"}})
async def delete_event(
    event_id: str, admin: Annotated[User, Depends(admin_user)], service: FromDishka[AdminEventsService]
) -> EventDeleteResponse:
    """Delete and archive an event by ID."""
    deleted = await service.delete_event(event_id=event_id, deleted_by=admin.email)
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")

    return EventDeleteResponse(message="Event deleted and archived", event_id=event_id)
