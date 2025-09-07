import csv
import json
from datetime import datetime, timezone
from io import StringIO

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.api.dependencies import AuthService, require_admin_guard
from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.core.service_dependencies import AdminEventsRepositoryDep
from app.domain.admin.replay_models import ReplayQuery, ReplaySessionFields
from app.domain.enums.replay import ReplayTarget, ReplayType
from app.domain.events.event_models import EventFilter, ReplaySessionStatus
from app.domain.replay.models import ReplayConfig, ReplayFilter
from app.infrastructure.mappers.event_mapper import (
    EventDetailMapper,
    EventExportRowMapper,
    EventMapper,
    EventStatisticsMapper,
    EventSummaryMapper,
)
from app.infrastructure.mappers.replay_mapper import ReplaySessionMapper
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
from app.services.replay_service import ReplayService

router = APIRouter(
    prefix="/admin/events",
    tags=["admin-events"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_admin_guard)]
)


@router.post("/browse")
async def browse_events(
        request: EventBrowseRequest,
        repository: AdminEventsRepositoryDep
) -> EventBrowseResponse:
    try:
        # Convert request to domain model
        event_filter = EventFilter(
            event_types=request.filters.event_types,
            aggregate_id=request.filters.aggregate_id,
            correlation_id=request.filters.correlation_id,
            user_id=request.filters.user_id,
            service_name=request.filters.service_name,
            start_time=request.filters.start_time,
            end_time=request.filters.end_time,
            search_text=request.filters.search_text
        )

        result = await repository.browse_events(
            filter=event_filter,
            skip=request.skip,
            limit=request.limit,
            sort_by=request.sort_by,
            sort_order=request.sort_order
        )

        # Convert domain model to response
        event_mapper = EventMapper()
        return EventBrowseResponse(
            events=[jsonable_encoder(event_mapper.to_dict(event)) for event in result.events],
            total=result.total,
            skip=result.skip,
            limit=result.limit
        )

    except Exception as e:
        logger.error(f"Error browsing events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_event_stats(
        repository: AdminEventsRepositoryDep,
        hours: int = Query(default=24, le=168),
) -> EventStatsResponse:
    try:
        stats = await repository.get_event_stats(hours=hours)
        stats_mapper = EventStatisticsMapper()
        return EventStatsResponse(**stats_mapper.to_dict(stats))

    except Exception as e:
        logger.error(f"Error getting event stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}")
async def get_event_detail(
        event_id: str,
        repository: AdminEventsRepositoryDep
) -> EventDetailResponse:
    try:
        result = await repository.get_event_detail(event_id)

        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        # Convert domain model to response
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
        logger.error(f"Error getting event detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/replay")
async def replay_events(
        request: EventReplayRequest,
        background_tasks: BackgroundTasks,
        repository: AdminEventsRepositoryDep,
        replay_service: FromDishka[ReplayService]
) -> EventReplayResponse:
    try:
        # Build query from request
        replay_query = ReplayQuery(
            event_ids=request.event_ids,
            correlation_id=request.correlation_id,
            aggregate_id=request.aggregate_id,
            start_time=request.start_time,
            end_time=request.end_time
        )
        query = repository.build_replay_query(replay_query)

        if not query:
            raise HTTPException(
                status_code=400,
                detail="Must specify at least one filter for replay"
            )

        replay_correlation_id = f"replay_{CorrelationContext.get_correlation_id()}"

        # Prepare replay session
        try:
            session_data = await repository.prepare_replay_session(
                query=query,
                dry_run=request.dry_run,
                replay_correlation_id=replay_correlation_id,
                max_events=1000
            )
        except ValueError as e:
            if "No events found" in str(e):
                raise HTTPException(status_code=404, detail=str(e))
            elif "Too many events" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise

        # If dry run, return preview
        if request.dry_run:
            summary_mapper = EventSummaryMapper()
            return EventReplayResponse(
                dry_run=True,
                total_events=session_data.total_events,
                replay_correlation_id=replay_correlation_id,
                status="Preview",
                events_preview=[jsonable_encoder(summary_mapper.to_dict(e)) for e in session_data.events_preview]
            )

        # Create replay configuration with custom query
        logger.info(f"Replay query for session: {query}")
        replay_filter = ReplayFilter(custom_query=query)
        replay_config = ReplayConfig(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA if request.target_service else ReplayTarget.TEST,
            filter=replay_filter,
            speed_multiplier=1.0,
            preserve_timestamps=False,
            batch_size=100,
            max_events=1000,
            skip_errors=True
        )

        # Create replay session using the config
        replay_response = await replay_service.create_session(replay_config)
        session_id = replay_response.session_id

        # Update the existing replay session with additional metadata
        await repository.update_replay_session(
            session_id=str(session_id),
            updates={
                ReplaySessionFields.TOTAL_EVENTS: session_data.total_events,
                ReplaySessionFields.CORRELATION_ID: replay_correlation_id,
                ReplaySessionFields.STATUS: ReplaySessionStatus.SCHEDULED
            }
        )

        # Start the replay session
        background_tasks.add_task(
            replay_service.start_session,
            session_id
        )

        return EventReplayResponse(
            dry_run=False,
            total_events=session_data.total_events,
            replay_correlation_id=replay_correlation_id,
            session_id=str(session_id),
            status="Replay scheduled in background"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error replaying events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/replay/{session_id}/status")
async def get_replay_status(
        session_id: str,
        repository: AdminEventsRepositoryDep
) -> EventReplayStatusResponse:
    try:
        status = await repository.get_replay_status_with_progress(session_id)

        if not status:
            raise HTTPException(status_code=404, detail="Replay session not found")

        replay_mapper = ReplaySessionMapper()
        return EventReplayStatusResponse(**replay_mapper.status_detail_to_dict(status))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting replay status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{event_id}")
async def delete_event(
        event_id: str,
        repository: AdminEventsRepositoryDep,
        request: Request,
        auth_service: FromDishka[AuthService]
) -> EventDeleteResponse:
    current_user = await auth_service.require_admin(request)
    try:
        logger.warning(
            f"Admin {current_user.email} attempting to delete event {event_id}"
        )

        # Get event details first for archiving
        event_detail = await repository.get_event_detail(event_id)
        if not event_detail:
            raise HTTPException(status_code=404, detail="Event not found")

        # Archive the event before deletion
        await repository.archive_event(event_detail.event, current_user.email)

        # Delete the event
        deleted = await repository.delete_event(event_id)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete event")

        logger.info(
            f"Event {event_id} deleted by {current_user.email}",
            extra={
                "event_type": event_detail.event.event_type,
                "correlation_id": event_detail.event.correlation_id
            }
        )

        return EventDeleteResponse(
            message="Event deleted and archived",
            event_id=event_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/csv")
async def export_events_csv(
        repository: AdminEventsRepositoryDep,
        event_types: str | None = Query(None, description="Comma-separated event types"),
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = Query(default=10000, le=50000),
) -> StreamingResponse:
    try:
        # Create filter for export
        export_filter = EventFilter(
            event_types=event_types.split(",") if event_types else None,
            start_time=datetime.fromtimestamp(start_time, tz=timezone.utc) if start_time else None,
            end_time=datetime.fromtimestamp(end_time, tz=timezone.utc) if end_time else None
        )

        export_rows = await repository.export_events_csv(export_filter)

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "Event ID", "Event Type", "Timestamp", "Correlation ID",
            "Aggregate ID", "User ID", "Service", "Status", "Error"
        ])

        writer.writeheader()
        row_mapper = EventExportRowMapper()
        for row in export_rows[:limit]:
            writer.writerow(row_mapper.to_dict(row))

        output.seek(0)
        filename = f"events_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        logger.error(f"Error exporting events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/json")
async def export_events_json(
        repository: AdminEventsRepositoryDep,
        event_types: str | None = Query(None, description="Comma-separated event types"),
        aggregate_id: str | None = Query(None, description="Aggregate ID filter"),
        correlation_id: str | None = Query(None, description="Correlation ID filter"),
        user_id: str | None = Query(None, description="User ID filter"),
        service_name: str | None = Query(None, description="Service name filter"),
        start_time: str | None = Query(None, description="Start time (ISO format)"),
        end_time: str | None = Query(None, description="End time (ISO format)"),
        limit: int = Query(default=10000, le=50000),
) -> StreamingResponse:
    """Export events as JSON with comprehensive filtering."""
    try:
        # Create filter for export
        export_filter = EventFilter(
            event_types=event_types.split(",") if event_types else None,
            aggregate_id=aggregate_id,
            correlation_id=correlation_id,
            user_id=user_id,
            service_name=service_name,
            start_time=datetime.fromisoformat(start_time) if start_time else None,
            end_time=datetime.fromisoformat(end_time) if end_time else None
        )

        # Get events from repository
        result = await repository.browse_events(
            filter=export_filter,
            skip=0,
            limit=limit,
            sort_by="timestamp",
            sort_order=-1
        )

        # Convert events to JSON-serializable format
        event_mapper = EventMapper()
        events_data = []
        for event in result.events:
            event_dict = event_mapper.to_dict(event)
            # Convert datetime fields to ISO format for JSON serialization
            # MongoDB always returns datetime objects, so we can use isinstance
            for field in ["timestamp", "created_at", "updated_at", "stored_at", "ttl_expires_at"]:
                if field in event_dict and isinstance(event_dict[field], datetime):
                    event_dict[field] = event_dict[field].isoformat()
            events_data.append(event_dict)

        # Create export metadata
        export_data = {
            "export_metadata": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "total_events": len(events_data),
                "filters_applied": {
                    "event_types": event_types.split(",") if event_types else None,
                    "aggregate_id": aggregate_id,
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "service_name": service_name,
                    "start_time": start_time,
                    "end_time": end_time
                },
                "export_limit": limit
            },
            "events": events_data
        }

        # Convert to JSON string with pretty formatting
        json_content = json.dumps(export_data, indent=2, default=str)
        filename = f"events_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        logger.error(f"Error exporting events as JSON: {e}")
        raise HTTPException(status_code=500, detail=str(e))
