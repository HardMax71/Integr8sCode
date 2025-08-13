from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app.api.dependencies import get_current_user, require_admin
from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.db.repositories.event_repository import EventRepository, get_event_repository
from app.domain.events.event_models import EventFilter
from app.schemas_pydantic.events import (
    DeleteEventResponse,
    EventAggregationRequest,
    EventFilterRequest,
    EventListResponse,
    EventResponse,
    EventStatistics,
    PublishEventRequest,
    PublishEventResponse,
    ReplayAggregateResponse,
    SortOrder,
)
from app.schemas_pydantic.user import User, UserResponse
from app.services.kafka_event_service import KafkaEventService, get_event_service

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/executions/{execution_id}", response_model=EventListResponse)
async def get_execution_events(
        execution_id: str,
        include_system_events: bool = Query(
            False,
            description="Include system-generated events"
        ),
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventListResponse:
    """Get all events for a specific execution"""
    try:
        events = await event_repository.get_execution_events_with_access_check(
            execution_id=execution_id,
            user_id=current_user.user_id,
            user_role=current_user.role,
            include_system_events=include_system_events
        )

        if events is None:
            raise HTTPException(status_code=403, detail="Access denied")

        event_responses = [EventResponse(**event.to_dict()) for event in events]

        return EventListResponse(
            events=event_responses,
            total=len(event_responses),
            limit=1000,
            skip=0,
            has_more=False
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving execution events: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve events")


@router.get("/user", response_model=EventListResponse)
async def get_user_events(
        event_types: Optional[List[str]] = Query(None),
        start_time: Optional[datetime] = Query(None),
        end_time: Optional[datetime] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        skip: int = Query(0, ge=0),
        sort_order: SortOrder = Query(SortOrder.DESC),
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventListResponse:
    """Get events for the current user"""
    try:
        result = await event_repository.get_user_events_paginated(
            user_id=current_user.user_id,
            event_types=event_types,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            skip=skip,
            sort_order=sort_order
        )

        event_responses = [EventResponse(**event.to_dict()) for event in result.events]

        return EventListResponse(
            events=event_responses,
            total=result.total,
            limit=limit,
            skip=skip,
            has_more=result.has_more
        )

    except Exception as e:
        logger.error(f"Error retrieving user events: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve events")


@router.post("/query", response_model=EventListResponse)
async def query_events(
        request: EventFilterRequest,
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventListResponse:
    """Query events with advanced filters"""
    try:
        # Convert request to EventFilter
        event_filter = EventFilter(
            event_types=[str(et) for et in request.event_types] if request.event_types else None,
            aggregate_id=request.aggregate_id,
            correlation_id=request.correlation_id,
            user_id=request.user_id
        )

        result = await event_repository.query_events_advanced(
            user_id=current_user.user_id,
            user_role=current_user.role,
            filters=event_filter
        )

        if result is None:
            raise HTTPException(
                status_code=403,
                detail="Cannot query other users' events"
            )

        event_responses = [EventResponse(**event.to_dict()) for event in result.events]

        return EventListResponse(
            events=event_responses,
            total=result.total,
            limit=result.limit,
            skip=result.skip,
            has_more=result.has_more
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying events: {e}")
        raise HTTPException(status_code=500, detail="Failed to query events")


@router.get("/correlation/{correlation_id}", response_model=EventListResponse)
async def get_events_by_correlation(
        correlation_id: str,
        include_all_users: bool = Query(
            False,
            description="Include events from all users (admin only)"
        ),
        limit: int = Query(100, ge=1, le=1000),
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventListResponse:
    """Get all events with the same correlation ID"""
    try:
        events = await event_repository.get_events_by_correlation_with_access(
            correlation_id=correlation_id,
            user_id=current_user.user_id,
            user_role=current_user.role,
            include_all_users=include_all_users,
            limit=limit
        )

        event_responses = [EventResponse(**event.to_dict()) for event in events]

        return EventListResponse(
            events=event_responses,
            total=len(event_responses),
            limit=limit,
            skip=0,
            has_more=False
        )

    except Exception as e:
        logger.error(f"Error getting events by correlation ID: {e}")
        raise HTTPException(status_code=500, detail="Failed to get correlated events")


@router.get("/current-request", response_model=EventListResponse)
async def get_current_request_events(
        limit: int = Query(100, ge=1, le=1000),
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventListResponse:
    """Get all events for the current request (using correlation ID from context)"""
    try:
        correlation_id = CorrelationContext.get_correlation_id()
        if not correlation_id:
            return EventListResponse(
                events=[],
                total=0,
                limit=limit,
                skip=0,
                has_more=False
            )

        events = await event_repository.get_events_by_correlation_with_access(
            correlation_id=correlation_id,
            user_id=current_user.user_id,
            user_role=current_user.role,
            include_all_users=False,
            limit=limit
        )

        event_responses = [EventResponse(**event.to_dict()) for event in events]

        return EventListResponse(
            events=event_responses,
            total=len(event_responses),
            limit=limit,
            skip=0,
            has_more=False
        )

    except Exception as e:
        logger.error(f"Error getting current request events: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current request events")


@router.get("/statistics", response_model=EventStatistics)
async def get_event_statistics(
        start_time: Optional[datetime] = Query(
            None,
            description="Start time for statistics (defaults to 24 hours ago)"
        ),
        end_time: Optional[datetime] = Query(
            None,
            description="End time for statistics (defaults to now)"
        ),
        include_all_users: bool = Query(
            False,
            description="Include stats from all users (admin only)"
        ),
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventStatistics:
    """Get event statistics"""
    try:
        if not start_time:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        if not end_time:
            end_time = datetime.now(timezone.utc)

        stats = await event_repository.get_event_statistics_with_access(
            user_id=current_user.user_id,
            user_role=current_user.role,
            start_time=start_time,
            end_time=end_time,
            include_all_users=include_all_users
        )

        return EventStatistics(**stats.to_dict())

    except Exception as e:
        logger.error(f"Error retrieving event statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve statistics")


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
        event_id: str,
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> EventResponse:
    """Get a specific event by ID"""
    try:
        event = await event_repository.get_event_with_access_check(
            event_id=event_id,
            user_id=current_user.user_id,
            user_role=current_user.role
        )

        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        return EventResponse(**event.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving event: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve event")


@router.post("/publish", response_model=PublishEventResponse)
async def publish_custom_event(
        event_request: PublishEventRequest,
        request: Request,
        current_user: UserResponse = Depends(require_admin),
        event_service: KafkaEventService = Depends(get_event_service)
) -> PublishEventResponse:
    """Publish a custom event (admin only)"""
    try:
        user = User.from_response(current_user)

        event_id = await event_service.publish_event(
            event_type=event_request.event_type,
            payload=event_request.payload,
            aggregate_id=event_request.aggregate_id,
            correlation_id=event_request.correlation_id,
            causation_id=event_request.causation_id,
            metadata=event_request.metadata,
            user=user,
            request=request
        )

        return PublishEventResponse(
            event_id=event_id,
            status="published",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Error publishing event: {e}")
        raise HTTPException(status_code=500, detail="Failed to publish event")


@router.post("/aggregate", response_model=List[Dict[str, Any]])
async def aggregate_events(
        aggregation: EventAggregationRequest,
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> List[Dict[str, Any]]:
    """Run aggregation pipeline on events (admin only for cross-user aggregations)"""
    try:
        result = await event_repository.aggregate_events_with_access(
            user_id=current_user.user_id,
            user_role=current_user.role,
            pipeline=aggregation.pipeline,
            limit=aggregation.limit
        )

        return result.results

    except Exception as e:
        logger.error(f"Error running aggregation: {e}")
        raise HTTPException(status_code=500, detail="Failed to run aggregation")


@router.get("/types/list", response_model=List[str])
async def list_event_types(
        current_user: UserResponse = Depends(get_current_user),
        event_repository: EventRepository = Depends(get_event_repository)
) -> List[str]:
    """Get list of all event types used by the current user"""
    try:
        event_types = await event_repository.list_event_types_for_user(
            user_id=current_user.user_id,
            user_role=current_user.role
        )

        return event_types

    except Exception as e:
        logger.error(f"Error listing event types: {e}")
        raise HTTPException(status_code=500, detail="Failed to list event types")


@router.delete("/{event_id}", response_model=DeleteEventResponse)
async def delete_event(
        event_id: str,
        background_tasks: BackgroundTasks,
        current_user: UserResponse = Depends(require_admin),
        event_repository: EventRepository = Depends(get_event_repository)
) -> DeleteEventResponse:
    """Delete an event (admin only, soft delete with archival)"""
    try:
        result = await event_repository.delete_event_with_archival(
            event_id=event_id,
            deleted_by=str(current_user.email)
        )

        if result is None:
            raise HTTPException(status_code=404, detail="Event not found")

        logger.warning(
            f"Event {event_id} deleted by admin {current_user.email}",
            extra={
                "event_type": result.event_type,
                "aggregate_id": result.aggregate_id,
                "correlation_id": result.correlation_id
            }
        )

        return DeleteEventResponse(
            message="Event deleted and archived",
            event_id=event_id,
            deleted_at=result.deleted_at.isoformat() if result.deleted_at else ""
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting event: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete event")


@router.post("/replay/{aggregate_id}", response_model=ReplayAggregateResponse)
async def replay_aggregate_events(
        aggregate_id: str,
        target_service: Optional[str] = Query(
            None,
            description="Service to replay events to"
        ),
        dry_run: bool = Query(
            True,
            description="If true, only show what would be replayed"
        ),
        current_user: UserResponse = Depends(require_admin),
        event_repository: EventRepository = Depends(get_event_repository),
        event_service: KafkaEventService = Depends(get_event_service)
) -> ReplayAggregateResponse:
    """Replay all events for an aggregate (admin only)"""
    try:
        replay_info = await event_repository.get_aggregate_replay_info(aggregate_id)

        if not replay_info:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for aggregate {aggregate_id}"
            )

        if dry_run:
            return ReplayAggregateResponse(
                dry_run=True,
                aggregate_id=aggregate_id,
                event_count=replay_info.event_count,
                event_types=replay_info.event_types,
                time_range=replay_info.time_range
            )

        # Perform actual replay
        replay_correlation_id = f"replay_{CorrelationContext.get_correlation_id()}"
        replayed_count = 0
        user = User.from_response(current_user)

        for event in replay_info.events:
            try:
                await event_service.publish_event(
                    event_type=f"replay.{event.event_type}",
                    payload=event.payload,
                    aggregate_id=aggregate_id,
                    correlation_id=replay_correlation_id,
                    causation_id=event.event_id,
                    metadata={
                        "original_event_id": event.event_id,
                        "replay_target": target_service,
                        "replayed_by": current_user.email,
                        "replayed_at": datetime.now(timezone.utc).isoformat()
                    },
                    user=user
                )
                replayed_count += 1
            except Exception as e:
                logger.error(f"Failed to replay event {event.event_id}: {e}")

        return ReplayAggregateResponse(
            dry_run=False,
            aggregate_id=aggregate_id,
            replayed_count=replayed_count,
            replay_correlation_id=replay_correlation_id
        )

    except Exception as e:
        logger.error(f"Error replaying aggregate events: {e}")
        raise HTTPException(status_code=500, detail="Failed to replay events")
