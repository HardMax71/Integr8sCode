from datetime import datetime
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.api.dependencies import admin_user
from app.core.correlation import CorrelationContext
from app.domain.enums.events import EventType
from app.infrastructure.mappers import (
    AdminReplayApiMapper,
    EventDetailMapper,
    EventFilterMapper,
    EventMapper,
    EventStatisticsMapper,
    ReplaySessionMapper,
)
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
from app.schemas_pydantic.admin_events import EventFilter as AdminEventFilter
from app.schemas_pydantic.user import UserResponse
from app.services.admin import AdminEventsService

router = APIRouter(
    prefix="/admin/events",
    tags=["admin-events"],
    route_class=DishkaRoute,
    dependencies=[Depends(admin_user)]
)


@router.post("/browse")
async def browse_events(
        request: EventBrowseRequest,
        service: FromDishka[AdminEventsService]
) -> EventBrowseResponse:
    try:
        event_filter = EventFilterMapper.from_admin_pydantic(request.filters)

        result = await service.browse_events(
            filter=event_filter,
            skip=request.skip,
            limit=request.limit,
            sort_by=request.sort_by,
            sort_order=request.sort_order
        )

        event_mapper = EventMapper()
        return EventBrowseResponse(
            events=[jsonable_encoder(event_mapper.to_dict(event)) for event in result.events],
            total=result.total,
            skip=result.skip,
            limit=result.limit
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_event_stats(
        service: FromDishka[AdminEventsService],
        hours: int = Query(default=24, le=168),
) -> EventStatsResponse:
    try:
        stats = await service.get_event_stats(hours=hours)
        stats_mapper = EventStatisticsMapper()
        return EventStatsResponse(**stats_mapper.to_dict(stats))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}")
async def get_event_detail(
        event_id: str,
        service: FromDishka[AdminEventsService]
) -> EventDetailResponse:
    try:
        result = await service.get_event_detail(event_id)

        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        detail_mapper = EventDetailMapper()
        serialized_result = jsonable_encoder(detail_mapper.to_dict(result))
        return EventDetailResponse(
            event=serialized_result["event"],
            related_events=serialized_result["related_events"],
            timeline=serialized_result["timeline"]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/replay")
async def replay_events(
        request: EventReplayRequest,
        background_tasks: BackgroundTasks,
        service: FromDishka[AdminEventsService]
) -> EventReplayResponse:
    try:
        replay_correlation_id = f"replay_{CorrelationContext.get_correlation_id()}"
        rq = AdminReplayApiMapper.request_to_query(request)
        try:
            result = await service.prepare_or_schedule_replay(
                replay_query=rq,
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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/replay/{session_id}/status")
async def get_replay_status(
        session_id: str,
        service: FromDishka[AdminEventsService]
) -> EventReplayStatusResponse:
    try:
        status = await service.get_replay_status(session_id)

        if not status:
            raise HTTPException(status_code=404, detail="Replay session not found")

        replay_mapper = ReplaySessionMapper()
        return EventReplayStatusResponse(**replay_mapper.status_detail_to_dict(status))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{event_id}")
async def delete_event(
        event_id: str,
        admin: Annotated[UserResponse, Depends(admin_user)],
        service: FromDishka[AdminEventsService]
) -> EventDeleteResponse:
    try:
        deleted = await service.delete_event(event_id=event_id, deleted_by=admin.email)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete event")

        return EventDeleteResponse(
            message="Event deleted and archived",
            event_id=event_id
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/csv")
async def export_events_csv(
        service: FromDishka[AdminEventsService],
        event_types: list[EventType] | None = Query(None, description="Event types (repeat param for multiple)"),
        start_time: datetime | None = Query(None, description="Start time"),
        end_time: datetime | None = Query(None, description="End time"),
        limit: int = Query(default=10000, le=50000),
) -> StreamingResponse:
    try:
        export_filter = EventFilterMapper.from_admin_pydantic(
            AdminEventFilter(
                event_types=event_types,
                start_time=start_time,
                end_time=end_time,
            )
        )
        result = await service.export_events_csv_content(filter=export_filter, limit=limit)
        return StreamingResponse(
            iter([result.content]),
            media_type=result.media_type,
            headers={"Content-Disposition": f"attachment; filename={result.filename}"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/json")
async def export_events_json(
        service: FromDishka[AdminEventsService],
        event_types: list[EventType] | None = Query(None, description="Event types (repeat param for multiple)"),
        aggregate_id: str | None = Query(None, description="Aggregate ID filter"),
        correlation_id: str | None = Query(None, description="Correlation ID filter"),
        user_id: str | None = Query(None, description="User ID filter"),
        service_name: str | None = Query(None, description="Service name filter"),
        start_time: datetime | None = Query(None, description="Start time"),
        end_time: datetime | None = Query(None, description="End time"),
        limit: int = Query(default=10000, le=50000),
) -> StreamingResponse:
    """Export events as JSON with comprehensive filtering."""
    try:
        export_filter = EventFilterMapper.from_admin_pydantic(
            AdminEventFilter(
                event_types=event_types,
                aggregate_id=aggregate_id,
                correlation_id=correlation_id,
                user_id=user_id,
                service_name=service_name,
                start_time=start_time,
                end_time=end_time,
            )
        )
        result = await service.export_events_json_content(filter=export_filter, limit=limit)
        return StreamingResponse(
            iter([result.content]),
            media_type=result.media_type,
            headers={"Content-Disposition": f"attachment; filename={result.filename}"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
