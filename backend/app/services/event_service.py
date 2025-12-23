from datetime import datetime
from typing import Any, Dict, List

from pymongo import ASCENDING, DESCENDING

from app.db.repositories.event_repository import EventRepository
from app.domain.enums.user import UserRole
from app.domain.events import (
    Event,
    EventAggregationResult,
    EventFilter,
    EventListResult,
    EventReplayInfo,
    EventStatistics,
)
from app.infrastructure.mappers import EventFilterMapper


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
    ) -> List[Event] | None:
        events = await self.repository.get_events_by_aggregate(aggregate_id=execution_id, limit=1000)
        if not events:
            return []

        owner = None
        for e in events:
            if e.metadata and e.metadata.user_id:
                owner = e.metadata.user_id
                break

        if owner and owner != user_id and user_role != UserRole.ADMIN:
            return None

        if not include_system_events:
            events = [e for e in events if not (e.metadata and e.metadata.service_name.startswith("system-"))]

        return events

    async def get_user_events_paginated(
        self,
        user_id: str,
        event_types: List[str] | None = None,
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
        sort_order: Any = "desc",
        limit: int = 100,
        skip: int = 0,
    ) -> EventListResult | None:
        # Access control
        if filters.user_id and filters.user_id != user_id and user_role != UserRole.ADMIN:
            return None

        query = EventFilterMapper.to_mongo_query(filters)
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
        direction = DESCENDING if str(sort_order).lower() == "desc" else ASCENDING

        # Pagination and sorting from request
        return await self.repository.query_events_generic(
            query=query,
            sort_field=sort_field,
            sort_direction=direction,
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
    ) -> List[Event]:
        events = await self.repository.get_events_by_correlation(correlation_id=correlation_id, limit=limit)
        if not include_all_users or user_role != UserRole.ADMIN:
            events = [e for e in events if (e.metadata and e.metadata.user_id == user_id)]
        return events

    async def get_event_statistics(
        self,
        user_id: str,
        user_role: UserRole,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        include_all_users: bool = False,
    ) -> EventStatistics:
        match = {} if include_all_users else self._build_user_filter(user_id, user_role)
        return await self.repository.get_event_statistics_filtered(
            match=match,
            start_time=start_time,
            end_time=end_time,
        )

    async def get_event(
        self,
        event_id: str,
        user_id: str,
        user_role: UserRole,
    ) -> Event | None:
        event = await self.repository.get_event(event_id)
        if not event:
            return None
        event_user_id = event.metadata.user_id
        if event_user_id != user_id and user_role != UserRole.ADMIN:
            return None
        return event

    async def aggregate_events(
        self,
        user_id: str,
        user_role: UserRole,
        pipeline: List[Dict[str, Any]],
        limit: int = 100,
    ) -> EventAggregationResult:
        user_filter = self._build_user_filter(user_id, user_role)
        new_pipeline = list(pipeline)
        if user_filter:
            if new_pipeline and "$match" in new_pipeline[0]:
                new_pipeline[0]["$match"] = {"$and": [new_pipeline[0]["$match"], user_filter]}
            else:
                new_pipeline.insert(0, {"$match": user_filter})
        return await self.repository.aggregate_events(new_pipeline, limit=limit)

    async def list_event_types(
        self,
        user_id: str,
        user_role: UserRole,
    ) -> List[str]:
        match = self._build_user_filter(user_id, user_role)
        return await self.repository.list_event_types(match=match)

    async def delete_event_with_archival(
        self,
        event_id: str,
        deleted_by: str,
        deletion_reason: str = "Admin deletion via API",
    ) -> Event | None:
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
        event_types: List[str] | None = None,
        limit: int = 100,
    ) -> list[Event]:
        return await self.repository.get_events_by_aggregate(
            aggregate_id=aggregate_id,
            event_types=event_types,
            limit=limit,
        )
