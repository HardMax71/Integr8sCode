from datetime import datetime
from typing import Any

from app.db.repositories import EventRepository
from app.domain.enums import EventType, UserRole
from app.domain.events import (
    ArchivedEvent,
    DomainEvent,
    EventFilter,
    EventListResult,
    EventReplayInfo,
    EventStatistics,
)


def _filter_to_mongo_query(flt: EventFilter) -> dict[str, Any]:
    """Convert EventFilter to MongoDB query dict."""
    query: dict[str, Any] = {}

    if flt.event_types:
        query["event_type"] = {"$in": flt.event_types}
    if flt.aggregate_id:
        query["aggregate_id"] = flt.aggregate_id
    if flt.correlation_id:
        query["metadata.correlation_id"] = flt.correlation_id
    if flt.user_id:
        query["metadata.user_id"] = flt.user_id
    if flt.service_name:
        query["metadata.service_name"] = flt.service_name
    if getattr(flt, "status", None):
        query["status"] = flt.status

    if flt.start_time or flt.end_time:
        time_query: dict[str, Any] = {}
        if flt.start_time:
            time_query["$gte"] = flt.start_time
        if flt.end_time:
            time_query["$lte"] = flt.end_time
        query["timestamp"] = time_query

    if flt.search_text:
        query["$text"] = {"$search": flt.search_text}

    return query


class EventService:
    def __init__(self, repository: EventRepository):
        self.repository = repository

    def _build_user_filter(self, user_id: str, user_role: UserRole) -> dict[str, object]:
        """Build user filter based on role. Returns empty dict ( = see everything) for admins."""
        if user_role == UserRole.ADMIN:
            return {}
        return {"metadata.user_id": user_id}

    async def get_execution_events(
        self,
        execution_id: str,
        user_id: str,
        user_role: UserRole,
        include_system_events: bool = False,
        limit: int = 1000,
        skip: int = 0,
    ) -> EventListResult | None:
        # Filter system events at DB level for accurate pagination
        result = await self.repository.get_execution_events(
            execution_id=execution_id,
            limit=limit,
            skip=skip,
            exclude_system_events=not include_system_events,
        )
        if not result.events:
            return EventListResult(events=[], total=0, skip=skip, limit=limit, has_more=False)

        owner = None
        for e in result.events:
            if e.metadata.user_id:
                owner = e.metadata.user_id
                break

        if owner and owner != user_id and user_role != UserRole.ADMIN:
            return None

        return result

    async def get_user_events_paginated(
        self,
        user_id: str,
        event_types: list[EventType] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        skip: int = 0,
        sort_order: str = "desc",
    ) -> EventListResult:
        return await self.repository.get_user_events_paginated(
            user_id=user_id,
            event_types=event_types,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            skip=skip,
            sort_order=sort_order,
        )

    async def query_events_advanced(
        self,
        user_id: str,
        user_role: UserRole,
        filters: EventFilter,
        sort_by: str = "timestamp",
        limit: int = 100,
        skip: int = 0,
    ) -> EventListResult | None:
        # Access control
        if filters.user_id and filters.user_id != user_id and user_role != UserRole.ADMIN:
            return None

        query = _filter_to_mongo_query(filters)
        if not filters.user_id and user_role != UserRole.ADMIN:
            query["metadata.user_id"] = user_id

        # Sort field mapping
        field_map = {
            "timestamp": "timestamp",
            "event_type": "event_type",
            "aggregate_id": "aggregate_id",
            "correlation_id": "metadata.correlation_id",
            "stored_at": "stored_at",
        }
        sort_field = field_map.get(sort_by, "timestamp")

        return await self.repository.query_events(
            query=query,
            sort_field=sort_field,
            skip=skip,
            limit=limit,
        )

    async def get_events_by_correlation(
        self,
        correlation_id: str,
        user_id: str,
        user_role: UserRole,
        include_all_users: bool = False,
        limit: int = 100,
        skip: int = 0,
    ) -> EventListResult:
        filter_user = user_id if not include_all_users or user_role != UserRole.ADMIN else None
        return await self.repository.get_events_by_correlation(
            correlation_id=correlation_id, limit=limit, skip=skip, user_id=filter_user,
        )

    async def get_event_statistics(
        self,
        user_id: str,
        user_role: UserRole,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        include_all_users: bool = False,
    ) -> EventStatistics:
        match = {} if include_all_users else self._build_user_filter(user_id, user_role)
        return await self.repository.get_event_statistics(
            start_time=start_time,
            end_time=end_time,
            match=match or None,
        )

    async def get_event(
        self,
        event_id: str,
        user_id: str,
        user_role: UserRole,
    ) -> DomainEvent | None:
        event = await self.repository.get_event(event_id)
        if not event:
            return None
        event_user_id = event.metadata.user_id
        if event_user_id != user_id and user_role != UserRole.ADMIN:
            return None
        return event

    async def delete_event_with_archival(
        self,
        event_id: str,
        deleted_by: str,
        deletion_reason: str = "Admin deletion via API",
    ) -> ArchivedEvent | None:
        return await self.repository.delete_event_with_archival(
            event_id=event_id,
            deleted_by=deleted_by,
            deletion_reason=deletion_reason,
        )

    async def get_aggregate_replay_info(self, aggregate_id: str) -> EventReplayInfo | None:
        return await self.repository.get_aggregate_replay_info(aggregate_id)

    async def get_events_by_aggregate(
        self,
        aggregate_id: str,
        event_types: list[EventType] | None = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
        return await self.repository.get_events_by_aggregate(
            aggregate_id=aggregate_id,
            event_types=event_types,
            limit=limit,
        )
