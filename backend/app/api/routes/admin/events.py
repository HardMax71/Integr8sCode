import csv
import json
from datetime import datetime, timezone
from io import StringIO
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.dependencies import require_admin
from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository, get_admin_events_repository
from app.domain.admin.event_models import EventFilter
from app.domain.admin.replay_models import ReplayQuery, ReplaySession
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
from app.services.event_replay import EventReplayService, get_replay_service
from app.services.event_replay.replay_service import ReplayConfig, ReplayFilter, ReplayTarget, ReplayType

router = APIRouter(prefix="/admin/events", tags=["admin-events"])


@router.post("/browse")
async def browse_events(
        request: EventBrowseRequest,
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        current_user: UserResponse = Depends(require_admin)
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
        return EventBrowseResponse(
            events=[json.loads(json.dumps(event.to_dict(), default=str)) for event in result.events],
            total=result.total,
            skip=result.skip,
            limit=result.limit
        )

    except Exception as e:
        logger.error(f"Error browsing events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_event_stats(
        hours: int = Query(default=24, le=168),
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        current_user: UserResponse = Depends(require_admin)
) -> EventStatsResponse:
    try:
        stats = await repository.get_event_stats(hours=hours)
        return EventStatsResponse(**stats.to_dict())

    except Exception as e:
        logger.error(f"Error getting event stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}")
async def get_event_detail(
        event_id: str,
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        current_user: UserResponse = Depends(require_admin)
) -> EventDetailResponse:
    try:
        result = await repository.get_event_detail(event_id)

        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        # Convert domain model to response
        serialized_result = json.loads(json.dumps(result.to_dict(), default=str))
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
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        replay_service: EventReplayService = Depends(get_replay_service),
        current_user: UserResponse = Depends(require_admin)
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
            return EventReplayResponse(
                dry_run=True,
                total_events=session_data.total_events,
                replay_correlation_id=replay_correlation_id,
                status="Preview",
                events_preview=[json.loads(json.dumps(e.to_dict(), default=str)) for e in session_data.events_preview]
            )

        # Create replay configuration
        replay_filter = ReplayFilter(custom_query=query)
        replay_config = ReplayConfig(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA if request.target_service else ReplayTarget.TEST,
            filter=replay_filter
        )

        # Create and start replay session
        session_id = await replay_service.create_replay_session(replay_config)

        # Store replay session info in database for tracking
        from app.domain.admin.event_models import ReplaySessionStatus
        replay_session = ReplaySession(
            session_id=str(session_id),
            status=ReplaySessionStatus.SCHEDULED,
            total_events=session_data.total_events,
            correlation_id=replay_correlation_id,
            created_at=datetime.now(timezone.utc)
        )

        await repository.create_replay_session(replay_session)

        background_tasks.add_task(
            replay_service.start_replay,
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
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        current_user: UserResponse = Depends(require_admin),
) -> EventReplayStatusResponse:
    try:
        status = await repository.get_replay_status_with_progress(session_id)

        if not status:
            raise HTTPException(status_code=404, detail="Replay session not found")

        return EventReplayStatusResponse(**status.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting replay status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{event_id}")
async def delete_event(
        event_id: str,
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        current_user: UserResponse = Depends(require_admin)
) -> EventDeleteResponse:
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
        event_types: Optional[str] = Query(None, description="Comma-separated event types"),
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = Query(default=10000, le=50000),
        repository: AdminEventsRepository = Depends(get_admin_events_repository),
        current_user: UserResponse = Depends(require_admin)
) -> StreamingResponse:
    try:
        # Create filter for export
        export_filter = EventFilter(
            event_types=event_types.split(",") if event_types else None,
            start_time=start_time,
            end_time=end_time
        )

        export_rows = await repository.export_events_csv(export_filter)

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "Event ID", "Event Type", "Timestamp", "Correlation ID",
            "Aggregate ID", "User ID", "Service", "Status", "Error"
        ])

        writer.writeheader()
        for row in export_rows[:limit]:
            writer.writerow(row.to_dict())

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
