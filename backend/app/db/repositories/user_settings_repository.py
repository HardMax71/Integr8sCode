import logging
from datetime import datetime
from typing import List

from beanie.odm.enums import SortDirection
from beanie.operators import GT, LTE, In

from app.db.docs import EventDocument, UserSettingsDocument
from app.domain.enums.events import EventType


class UserSettingsRepository:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def get_snapshot(self, user_id: str) -> UserSettingsDocument | None:
        return await UserSettingsDocument.find_one({"user_id": user_id})

    async def create_snapshot(self, settings: UserSettingsDocument) -> None:
        existing = await self.get_snapshot(settings.user_id)
        if existing:
            settings.id = existing.id
        await settings.save()
        self.logger.info(f"Created settings snapshot for user {settings.user_id}")

    async def get_settings_events(
        self,
        user_id: str,
        event_types: List[EventType],
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> List[EventDocument]:
        aggregate_id = f"user_settings_{user_id}"
        conditions = [
            EventDocument.aggregate_id == aggregate_id,
            In(EventDocument.event_type, [str(et) for et in event_types]),
            GT(EventDocument.timestamp, since) if since else None,
            LTE(EventDocument.timestamp, until) if until else None,
        ]
        conditions = [c for c in conditions if c is not None]

        find_query = EventDocument.find(*conditions).sort([("timestamp", SortDirection.ASCENDING)])
        if limit:
            find_query = find_query.limit(limit)

        return await find_query.to_list()

    async def count_events_since_snapshot(self, user_id: str) -> int:
        aggregate_id = f"user_settings_{user_id}"
        snapshot = await self.get_snapshot(user_id)
        if not snapshot:
            return await EventDocument.find(EventDocument.aggregate_id == aggregate_id).count()

        return await EventDocument.find(
            EventDocument.aggregate_id == aggregate_id,
            GT(EventDocument.timestamp, snapshot.updated_at),
        ).count()

    async def count_events_for_user(self, user_id: str) -> int:
        return await EventDocument.find(EventDocument.aggregate_id == f"user_settings_{user_id}").count()

    async def delete_user_settings(self, user_id: str) -> None:
        doc = await self.get_snapshot(user_id)
        if doc:
            await doc.delete()
        await EventDocument.find(EventDocument.aggregate_id == f"user_settings_{user_id}").delete()
        self.logger.info(f"Deleted all settings data for user {user_id}")
