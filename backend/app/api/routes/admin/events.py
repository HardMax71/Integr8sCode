from datetime import datetime
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.dependencies import admin_user
from app.core.correlation import CorrelationContext
from app.domain.enums.events import EventType
from app.domain.events.event_models import EventFilter
from app.domain.replay import ReplayFilter
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
from app.schemas_pydantic.user import UserResponse
from app.services.admin import AdminEventsService

router = APIRouter(
    prefix="/admin/events", tags=["admin-events"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.post("/browse")
async def browse_events(request: EventBrowseRequest, service: FromDishka[AdminEventsService]) -> EventBrowseResponse:
    event_filter = EventFilter(**request.filters.model_dump())

    result = await service.browse_events(
        event_filter=event_filter,
        skip=request.skip,
        limit=request.limit,
        sort_by=request.sort_by,
        sort_order=request.sort_order,
    )

    return EventBrowseResponse(
        events=result.events,
        total=result.total,
        skip=result.skip,
        limit=result.limit,
    )


@router.get("/stats")
async def get_event_stats(
    service: FromDishka[AdminEventsService],
    hours: Annotated[int, Query(le=168)] = 24,
) -> EventStatsResponse:
    stats = await service.get_event_stats(hours=hours)
    return EventStatsResponse.model_validate(stats)


@router.get("/export/csv")
async def export_events_csv(
    service: FromDishka[AdminEventsService],
    event_types: Annotated[list[EventType] | None, Query(description="Event types (repeat param for multiple)")] = None,
    start_time: Annotated[datetime | None, Query(description="Start time")] = None,
    end_time: Annotated[datetime | None, Query(description="End time")] = None,
    limit: Annotated[int, Query(le=50000)] = 10000,
) -> StreamingResponse:
    export_filter = EventFilter(
        event_types=event_types,
        start_time=start_time,
        end_time=end_time,
    )
    result = await service.export_events_csv_content(event_filter=export_filter, limit=limit)
    return StreamingResponse(
        iter([result.content]),
        media_type=result.media_type,
        headers={"Content-Disposition": f"attachment; filename={result.file_name}"},
    )


@router.get("/export/json")
async def export_events_json(
    service: FromDishka[AdminEventsService],
    event_types: Annotated[list[EventType] | None, Query(description="Event types (repeat param for multiple)")] = None,
    aggregate_id: Annotated[str | None, Query(description="Aggregate ID filter")] = None,
    correlation_id: Annotated[str | None, Query(description="Correlation ID filter")] = None,
    user_id: Annotated[str | None, Query(description="User ID filter")] = None,
    service_name: Annotated[str | None, Query(description="Service name filter")] = None,
    start_time: Annotated[datetime | None, Query(description="Start time")] = None,
    end_time: Annotated[datetime | None, Query(description="End time")] = None,
    limit: Annotated[int, Query(le=50000)] = 10000,
) -> StreamingResponse:
    """Export events as JSON with comprehensive filtering."""
    export_filter = EventFilter(
        event_types=event_types,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        user_id=user_id,
        service_name=service_name,
        start_time=start_time,
        end_time=end_time,
    )
    result = await service.export_events_json_content(event_filter=export_filter, limit=limit)
    return StreamingResponse(
        iter([result.content]),
        media_type=result.media_type,
        headers={"Content-Disposition": f"attachment; filename={result.file_name}"},
    )


@router.get("/{event_id}")
async def get_event_detail(event_id: str, service: FromDishka[AdminEventsService]) -> EventDetailResponse:
    result = await service.get_event_detail(event_id)

    if not result:
        raise HTTPException(status_code=404, detail="Event not found")

    return EventDetailResponse(
        event=result.event,
        related_events=result.related_events,
        timeline=result.timeline,
    )


@router.post("/replay")
async def replay_events(
    request: EventReplayRequest, background_tasks: BackgroundTasks, service: FromDishka[AdminEventsService]
) -> EventReplayResponse:
    replay_correlation_id = f"replay_{CorrelationContext.get_correlation_id()}"
    replay_filter = ReplayFilter(
        event_ids=request.event_ids,
        correlation_id=request.correlation_id,
        aggregate_id=request.aggregate_id,
        start_time=request.start_time,
        end_time=request.end_time,
    )
    try:
        result = await service.prepare_or_schedule_replay(
            replay_filter=replay_filter,
            dry_run=request.dry_run,
            replay_correlation_id=replay_correlation_id,
            target_service=request.target_service,
        )
    except ValueError as e:
        msg = str(e)
        if "No events found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "Too many events" in msg:
            raise HTTPException(status_code=400, detail=msg)
        raise

    if not result.dry_run and result.session_id:
        background_tasks.add_task(service.start_replay_session, result.session_id)

    return EventReplayResponse(
        dry_run=result.dry_run,
        total_events=result.total_events,
        replay_correlation_id=result.replay_correlation_id,
        session_id=result.session_id,
        status=result.status,
        events_preview=result.events_preview,
    )


@router.get("/replay/{session_id}/status")
async def get_replay_status(session_id: str, service: FromDishka[AdminEventsService]) -> EventReplayStatusResponse:
    status = await service.get_replay_status(session_id)

    if not status:
        raise HTTPException(status_code=404, detail="Replay session not found")

    session = status.session
    estimated_completion = status.estimated_completion
    execution_results = status.execution_results
    return EventReplayStatusResponse(
        **{
            **session.model_dump(),
            "status": session.status,
            "estimated_completion": estimated_completion,
            "execution_results": execution_results,
        }
    )


@router.delete("/{event_id}")
async def delete_event(
    event_id: str, admin: Annotated[UserResponse, Depends(admin_user)], service: FromDishka[AdminEventsService]
) -> EventDeleteResponse:
    deleted = await service.delete_event(event_id=event_id, deleted_by=admin.email)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete event")

    return EventDeleteResponse(message="Event deleted and archived", event_id=event_id)
