from datetime import datetime

from app.db.repositories import EventRepository
from app.domain.enums import EventType, UserRole
from app.domain.events import ArchivedEvent, DomainEvent
from app.schemas_pydantic.events import EventListResult, EventReplayInfo, EventStatistics


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
