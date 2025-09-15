import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import AdminUser, CurrentUser
from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.core.utils import get_client_ip
from app.domain.events.event_models import EventFilter
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.mappers import EventMapper, EventStatisticsMapper
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
from app.schemas_pydantic.user import UserResponse
from app.services.event_service import EventService
from app.services.kafka_event_service import KafkaEventService
from app.settings import get_settings

router = APIRouter(prefix="/events",
                   tags=["events"],
                   route_class=DishkaRoute)


@router.get("/executions/{execution_id}/events",
            response_model=EventListResponse)
async def get_execution_events(
        execution_id: str,
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService],
        include_system_events: bool = Query(
            False,
            description="Include system-generated events"
        )
) -> EventListResponse:
    mapper = EventMapper()
    events = await event_service.get_execution_events(
        execution_id=execution_id,
        user_id=current_user.user_id,
        user_role=current_user.role,
        include_system_events=include_system_events
    )

    if events is None:
        raise HTTPException(status_code=403, detail="Access denied")

    event_responses = [EventResponse(**mapper.to_dict(event)) for event in events]

    return EventListResponse(
        events=event_responses,
        total=len(event_responses),
        limit=1000,
        skip=0,
        has_more=False
    )


@router.get("/user", response_model=EventListResponse)
async def get_user_events(
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService],
        event_types: List[str] | None = Query(None),
        start_time: datetime | None = Query(None),
        end_time: datetime | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        skip: int = Query(0, ge=0),
        sort_order: SortOrder = Query(SortOrder.DESC)
) -> EventListResponse:
    """Get events for the current user"""
    mapper = EventMapper()
    result = await event_service.get_user_events_paginated(
        user_id=current_user.user_id,
        event_types=event_types,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        skip=skip,
        sort_order=sort_order
    )

    event_responses = [EventResponse(**mapper.to_dict(event)) for event in result.events]

    return EventListResponse(
        events=event_responses,
        total=result.total,
        limit=limit,
        skip=skip,
        has_more=result.has_more
    )


@router.post("/query", response_model=EventListResponse)
async def query_events(
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        filter_request: EventFilterRequest,
        event_service: FromDishka[EventService],
) -> EventListResponse:
    mapper = EventMapper()
    event_filter = EventFilter(
        event_types=[str(et) for et in filter_request.event_types] if filter_request.event_types else None,
        aggregate_id=filter_request.aggregate_id,
        correlation_id=filter_request.correlation_id,
        user_id=filter_request.user_id,
        service_name=filter_request.service_name,
        start_time=filter_request.start_time,
        end_time=filter_request.end_time,
        text_search=filter_request.text_search,
    )

    result = await event_service.query_events_advanced(
        user_id=current_user.user_id,
        user_role=current_user.role,
        filters=event_filter,
        sort_by=filter_request.sort_by,
        sort_order=filter_request.sort_order,
        limit=filter_request.limit,
        skip=filter_request.skip
    )
    if result is None:
        raise HTTPException(
            status_code=403,
            detail="Cannot query other users' events"
        )

    event_responses = [EventResponse(**mapper.to_dict(event)) for event in result.events]

    return EventListResponse(
        events=event_responses,
        total=result.total,
        limit=result.limit,
        skip=result.skip,
        has_more=result.has_more
    )


@router.get("/correlation/{correlation_id}", response_model=EventListResponse)
async def get_events_by_correlation(
        correlation_id: str,
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService],
        include_all_users: bool = Query(
            False,
            description="Include events from all users (admin only)"
        ),
        limit: int = Query(100, ge=1, le=1000)
) -> EventListResponse:
    mapper = EventMapper()
    events = await event_service.get_events_by_correlation(
        correlation_id=correlation_id,
        user_id=current_user.user_id,
        user_role=current_user.role,
        include_all_users=include_all_users,
        limit=limit
    )

    event_responses = [EventResponse(**mapper.to_dict(event)) for event in events]

    return EventListResponse(
        events=event_responses,
        total=len(event_responses),
        limit=limit,
        skip=0,
        has_more=False
    )


@router.get("/current-request", response_model=EventListResponse)
async def get_current_request_events(
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService],
        limit: int = Query(100, ge=1, le=1000),
) -> EventListResponse:
    mapper = EventMapper()
    correlation_id = CorrelationContext.get_correlation_id()
    if not correlation_id:
        return EventListResponse(
            events=[],
            total=0,
            limit=limit,
            skip=0,
            has_more=False
        )

    events = await event_service.get_events_by_correlation(
        correlation_id=correlation_id,
        user_id=current_user.user_id,
        user_role=current_user.role,
        include_all_users=False,
        limit=limit
    )

    event_responses = [EventResponse(**mapper.to_dict(event)) for event in events]

    return EventListResponse(
        events=event_responses,
        total=len(event_responses),
        limit=limit,
        skip=0,
        has_more=False
    )


@router.get("/statistics", response_model=EventStatistics)
async def get_event_statistics(
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService],
        start_time: datetime | None = Query(
            None,
            description="Start time for statistics (defaults to 24 hours ago)"
        ),
        end_time: datetime | None = Query(
            None,
            description="End time for statistics (defaults to now)"
        ),
        include_all_users: bool = Query(
            False,
            description="Include stats from all users (admin only)"
        ),
) -> EventStatistics:
    if not start_time:
        start_time = datetime.now(timezone.utc) - timedelta(days=1)  # 24 hours ago
    if not end_time:
        end_time = datetime.now(timezone.utc)

    stats = await event_service.get_event_statistics(
        user_id=current_user.user_id,
        user_role=current_user.role,
        start_time=start_time,
        end_time=end_time,
        include_all_users=include_all_users
    )

    stats_mapper = EventStatisticsMapper()
    return EventStatistics(**stats_mapper.to_dict(stats))


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
        event_id: str,
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService]
) -> EventResponse:
    """Get a specific event by ID"""
    mapper = EventMapper()
    event = await event_service.get_event(
        event_id=event_id,
        user_id=current_user.user_id,
        user_role=current_user.role
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventResponse(**mapper.to_dict(event))


@router.post("/publish", response_model=PublishEventResponse)
async def publish_custom_event(
        admin: Annotated[UserResponse, Depends(AdminUser)],
        event_request: PublishEventRequest,
        request: Request,
        event_service: FromDishka[KafkaEventService]
) -> PublishEventResponse:
    settings = get_settings()
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

    return PublishEventResponse(
        event_id=event_id,
        status="published",
        timestamp=datetime.now(timezone.utc)
    )


@router.post("/aggregate", response_model=List[Dict[str, Any]])
async def aggregate_events(
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        aggregation: EventAggregationRequest,
        event_service: FromDishka[EventService],
) -> List[Dict[str, Any]]:
    result = await event_service.aggregate_events(
        user_id=current_user.user_id,
        user_role=current_user.role,
        pipeline=aggregation.pipeline,
        limit=aggregation.limit
    )

    return result.results


@router.get("/types/list", response_model=List[str])
async def list_event_types(
        current_user: Annotated[UserResponse, Depends(CurrentUser)],
        event_service: FromDishka[EventService]
) -> List[str]:
    event_types = await event_service.list_event_types(
        user_id=current_user.user_id,
        user_role=current_user.role
    )
    return event_types


@router.delete("/{event_id}", response_model=DeleteEventResponse)
async def delete_event(
        event_id: str,
        admin: Annotated[UserResponse, Depends(AdminUser)],
        event_service: FromDishka[EventService],
) -> DeleteEventResponse:
    result = await event_service.delete_event_with_archival(
        event_id=event_id,
        deleted_by=str(admin.email)
    )

    if result is None:
        raise HTTPException(status_code=404, detail="Event not found")

    logger.warning(
        f"Event {event_id} deleted by admin {admin.email}",
        extra={
            "event_type": result.event_type,
            "aggregate_id": result.aggregate_id,
            "correlation_id": result.correlation_id
        }
    )

    return DeleteEventResponse(
        message="Event deleted and archived",
        event_id=event_id,
        deleted_at=datetime.now(timezone.utc)
    )


@router.post("/replay/{aggregate_id}", response_model=ReplayAggregateResponse)
async def replay_aggregate_events(
        aggregate_id: str,
        admin: Annotated[UserResponse, Depends(AdminUser)],
        event_service: FromDishka[EventService],
        kafka_event_service: FromDishka[KafkaEventService],
        target_service: str | None = Query(
            None,
            description="Service to replay events to"
        ),
        dry_run: bool = Query(
            True,
            description="If true, only show what would be replayed"
        ),
) -> ReplayAggregateResponse:
    replay_info = await event_service.get_aggregate_replay_info(aggregate_id)
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
            start_time=replay_info.start_time,
            end_time=replay_info.end_time
        )

    # Perform actual replay
    replay_correlation_id = f"replay_{CorrelationContext.get_correlation_id()}"
    replayed_count = 0

    for i, event in enumerate(replay_info.events):
        # Rate limiting: pause every 100 events to prevent overwhelming the system
        if i > 0 and i % 100 == 0:
            await asyncio.sleep(0.1)

        try:
            settings = get_settings()
            meta = EventMetadata(
                service_name=settings.SERVICE_NAME,
                service_version=settings.SERVICE_VERSION,
                user_id=admin.user_id,
            )
            await kafka_event_service.publish_event(
                event_type=f"replay.{event.event_type}",
                payload=event.payload,
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
        replay_correlation_id=replay_correlation_id
    )
