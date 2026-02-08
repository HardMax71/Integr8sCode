import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import admin_user, current_user
from app.core.correlation import CorrelationContext
from app.core.utils import get_client_ip
from app.domain.enums import EventType, SortOrder, UserRole
from app.domain.events import BaseEvent, DomainEvent, EventFilter, EventMetadata
from app.domain.user import User
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.events import (
    DeleteEventResponse,
    EventAggregationRequest,
    EventFilterRequest,
    EventListResponse,
    EventStatistics,
    PublishEventRequest,
    PublishEventResponse,
    ReplayAggregateResponse,
)
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.kafka_event_service import KafkaEventService
from app.settings import Settings

router = APIRouter(prefix="/events", tags=["events"], route_class=DishkaRoute)


@router.get(
    "/executions/{execution_id}/events",
    response_model=EventListResponse,
    responses={403: {"model": ErrorResponse}},
)
async def get_execution_events(
    execution_id: str,
    current_user: Annotated[User, Depends(current_user)],
    event_service: FromDishka[EventService],
    execution_service: FromDishka[ExecutionService],
    include_system_events: Annotated[bool, Query(description="Include system-generated events")] = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> EventListResponse:
    """Get events for a specific execution."""
    # Check execution ownership first (before checking events)
    execution = await execution_service.get_execution_result(execution_id)
    if execution.user_id and execution.user_id != current_user.user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await event_service.get_execution_events(
        execution_id=execution_id,
        user_id=current_user.user_id,
        user_role=current_user.role,
        include_system_events=include_system_events,
        limit=limit,
        skip=skip,
    )

    if result is None:
        raise HTTPException(status_code=403, detail="Access denied")

    return EventListResponse(
        events=result.events,
        total=result.total,
        limit=limit,
        skip=skip,
        has_more=result.has_more,
    )


@router.get("/user", response_model=EventListResponse)
async def get_user_events(
    current_user: Annotated[User, Depends(current_user)],
    event_service: FromDishka[EventService],
    event_types: Annotated[list[EventType] | None, Query(description="Filter by event types")] = None,
    start_time: Annotated[datetime | None, Query(description="Filter events after this time")] = None,
    end_time: Annotated[datetime | None, Query(description="Filter events before this time")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
    sort_order: Annotated[SortOrder, Query(description="Sort order by timestamp")] = SortOrder.DESC,
) -> EventListResponse:
    """Get events for the current user."""
    result = await event_service.get_user_events_paginated(
        user_id=current_user.user_id,
        event_types=event_types,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        skip=skip,
        sort_order=sort_order,
    )

    return EventListResponse(
        events=result.events,
        total=result.total,
        limit=limit,
        skip=skip,
        has_more=result.has_more,
    )


@router.post("/query", response_model=EventListResponse, responses={403: {"model": ErrorResponse}})
async def query_events(
    current_user: Annotated[User, Depends(current_user)],
    filter_request: EventFilterRequest,
    event_service: FromDishka[EventService],
) -> EventListResponse:
    """Query events with advanced filters."""
    event_filter = EventFilter(
        event_types=filter_request.event_types,
        aggregate_id=filter_request.aggregate_id,
        correlation_id=filter_request.correlation_id,
        user_id=filter_request.user_id,
        service_name=filter_request.service_name,
        start_time=filter_request.start_time,
        end_time=filter_request.end_time,
        search_text=filter_request.search_text,
    )

    result = await event_service.query_events_advanced(
        user_id=current_user.user_id,
        user_role=current_user.role,
        filters=event_filter,
        sort_by=filter_request.sort_by,
        limit=filter_request.limit,
        skip=filter_request.skip,
    )
    if result is None:
        raise HTTPException(status_code=403, detail="Cannot query other users' events")

    return EventListResponse(
        events=result.events,
        total=result.total,
        limit=result.limit,
        skip=result.skip,
        has_more=result.has_more,
    )


@router.get("/correlation/{correlation_id}", response_model=EventListResponse)
async def get_events_by_correlation(
    correlation_id: str,
    current_user: Annotated[User, Depends(current_user)],
    event_service: FromDishka[EventService],
    include_all_users: Annotated[bool, Query(description="Include events from all users (admin only)")] = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> EventListResponse:
    """Get all events sharing a correlation ID."""
    result = await event_service.get_events_by_correlation(
        correlation_id=correlation_id,
        user_id=current_user.user_id,
        user_role=current_user.role,
        include_all_users=include_all_users,
        limit=limit,
        skip=skip,
    )

    return EventListResponse(
        events=result.events,
        total=result.total,
        limit=limit,
        skip=skip,
        has_more=result.has_more,
    )


@router.get("/current-request", response_model=EventListResponse)
async def get_current_request_events(
    current_user: Annotated[User, Depends(current_user)],
    event_service: FromDishka[EventService],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    skip: Annotated[int, Query(ge=0)] = 0,
) -> EventListResponse:
    """Get events associated with the current HTTP request's correlation ID."""
    correlation_id = CorrelationContext.get_correlation_id()
    if not correlation_id:
        return EventListResponse(events=[], total=0, limit=limit, skip=skip, has_more=False)

    result = await event_service.get_events_by_correlation(
        correlation_id=correlation_id,
        user_id=current_user.user_id,
        user_role=current_user.role,
        include_all_users=False,
        limit=limit,
        skip=skip,
    )

    return EventListResponse(
        events=result.events,
        total=result.total,
        limit=limit,
        skip=skip,
        has_more=result.has_more,
    )


@router.get("/statistics", response_model=EventStatistics)
async def get_event_statistics(
    current_user: Annotated[User, Depends(current_user)],
    event_service: FromDishka[EventService],
    start_time: Annotated[
        datetime | None, Query(description="Start time for statistics (defaults to 24 hours ago)")
    ] = None,
    end_time: Annotated[datetime | None, Query(description="End time for statistics (defaults to now)")] = None,
    include_all_users: Annotated[bool, Query(description="Include stats from all users (admin only)")] = False,
) -> EventStatistics:
    """Get aggregated event statistics for a time range."""
    if not start_time:
        start_time = datetime.now(timezone.utc) - timedelta(days=1)  # 24 hours ago
    if not end_time:
        end_time = datetime.now(timezone.utc)

    stats = await event_service.get_event_statistics(
        user_id=current_user.user_id,
        user_role=current_user.role,
        start_time=start_time,
        end_time=end_time,
        include_all_users=include_all_users,
    )

    return EventStatistics.model_validate(stats)


@router.get("/{event_id}", response_model=DomainEvent, responses={404: {"model": ErrorResponse}})
async def get_event(
    event_id: str, current_user: Annotated[User, Depends(current_user)], event_service: FromDishka[EventService]
) -> DomainEvent:
    """Get a specific event by ID."""
    event = await event_service.get_event(event_id=event_id, user_id=current_user.user_id, user_role=current_user.role)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/publish", response_model=PublishEventResponse)
async def publish_custom_event(
    admin: Annotated[User, Depends(admin_user)],
    event_request: PublishEventRequest,
    request: Request,
    event_service: FromDishka[KafkaEventService],
    settings: FromDishka[Settings],
) -> PublishEventResponse:
    """Publish a custom event to Kafka (admin only)."""
    base_meta = EventMetadata(
        service_name=settings.SERVICE_NAME,
        service_version=settings.SERVICE_VERSION,
        user_id=admin.user_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    # Merge any additional metadata provided in request (extra allowed)
    if event_request.metadata:
        base_meta = base_meta.model_copy(update=event_request.metadata)

    event_id = await event_service.publish_event(
        event_type=event_request.event_type,
        payload=event_request.payload,
        aggregate_id=event_request.aggregate_id,
        correlation_id=event_request.correlation_id,
        metadata=base_meta,
    )

    return PublishEventResponse(event_id=event_id, status="published", timestamp=datetime.now(timezone.utc))


@router.post("/aggregate", response_model=list[dict[str, Any]])
async def aggregate_events(
    current_user: Annotated[User, Depends(current_user)],
    aggregation: EventAggregationRequest,
    event_service: FromDishka[EventService],
) -> list[dict[str, Any]]:
    """Run a custom aggregation pipeline on the event store."""
    result = await event_service.aggregate_events(
        user_id=current_user.user_id,
        user_role=current_user.role,
        pipeline=aggregation.pipeline,
        limit=aggregation.limit,
    )

    return result.results


@router.get("/types/list", response_model=list[str])
async def list_event_types(
    current_user: Annotated[User, Depends(current_user)], event_service: FromDishka[EventService]
) -> list[str]:
    """List all distinct event types in the store."""
    event_types = await event_service.list_event_types(user_id=current_user.user_id, user_role=current_user.role)
    return event_types


@router.delete("/{event_id}", response_model=DeleteEventResponse, responses={404: {"model": ErrorResponse}})
async def delete_event(
    event_id: str,
    admin: Annotated[User, Depends(admin_user)],
    event_service: FromDishka[EventService],
    logger: FromDishka[logging.Logger],
) -> DeleteEventResponse:
    """Delete and archive an event (admin only)."""
    result = await event_service.delete_event_with_archival(event_id=event_id, deleted_by=str(admin.email))

    if result is None:
        raise HTTPException(status_code=404, detail="Event not found")

    logger.warning(
        "Event deleted by admin",
        extra={
            "event_id": event_id,
            "admin_email": admin.email,
            "event_type": result.event_type,
            "aggregate_id": result.aggregate_id,
            "correlation_id": result.metadata.correlation_id,
        },
    )

    return DeleteEventResponse(
        message="Event deleted and archived", event_id=event_id, deleted_at=datetime.now(timezone.utc)
    )


@router.post(
    "/replay/{aggregate_id}",
    response_model=ReplayAggregateResponse,
    responses={404: {"model": ErrorResponse}},
)
async def replay_aggregate_events(
    aggregate_id: str,
    admin: Annotated[User, Depends(admin_user)],
    event_service: FromDishka[EventService],
    kafka_event_service: FromDishka[KafkaEventService],
    settings: FromDishka[Settings],
    logger: FromDishka[logging.Logger],
    target_service: Annotated[str | None, Query(description="Service to replay events to")] = None,
    dry_run: Annotated[bool, Query(description="If true, only show what would be replayed")] = True,
) -> ReplayAggregateResponse:
    """Replay all events for an aggregate (admin only)."""
    replay_info = await event_service.get_aggregate_replay_info(aggregate_id)
    if not replay_info:
        raise HTTPException(status_code=404, detail=f"No events found for aggregate {aggregate_id}")

    if dry_run:
        return ReplayAggregateResponse(
            dry_run=True,
            aggregate_id=aggregate_id,
            event_count=replay_info.event_count,
            event_types=replay_info.event_types,
            start_time=replay_info.start_time,
            end_time=replay_info.end_time,
        )

    # Perform actual replay
    replay_correlation_id = f"replay_{CorrelationContext.get_correlation_id()}"
    replayed_count = 0

    for event in replay_info.events:
        try:
            meta = EventMetadata(
                service_name=settings.SERVICE_NAME,
                service_version=settings.SERVICE_VERSION,
                user_id=admin.user_id,
            )
            # Extract payload fields (exclude base event fields + event_type discriminator)
            base_fields = set(BaseEvent.model_fields.keys()) | {"event_type"}
            extra_fields = {k: v for k, v in event.model_dump().items() if k not in base_fields}
            await kafka_event_service.publish_event(
                event_type=event.event_type,
                payload=extra_fields,
                aggregate_id=aggregate_id,
                correlation_id=replay_correlation_id,
                metadata=meta,
            )
            replayed_count += 1
        except Exception as e:
            logger.error(f"Failed to replay event {event.event_id}: {e}")

    return ReplayAggregateResponse(
        dry_run=False,
        aggregate_id=aggregate_id,
        replayed_count=replayed_count,
        replay_correlation_id=replay_correlation_id,
    )
