import logging
from datetime import datetime

from beanie.odm.enums import SortDirection
from beanie.operators import GT, LTE, In

from app.db.docs import EventDocument, UserSettingsDocument, UserSettingsSnapshotDocument
from app.domain.enums.events import EventType
from app.domain.user.settings_models import DomainUserSettings, DomainUserSettingsChangedEvent


class UserSettingsRepository:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        doc = await UserSettingsDocument.find_one({"user_id": user_id})
        if not doc:
            return None
        return DomainUserSettings.model_validate(doc, from_attributes=True)

    async def create_snapshot(self, settings: DomainUserSettings) -> None:
        existing = await UserSettingsDocument.find_one({"user_id": settings.user_id})
        doc = UserSettingsDocument(**settings.model_dump())
        if existing:
            doc.id = existing.id
        await doc.save()
        self.logger.info(f"Created settings snapshot for user {settings.user_id}")

    async def get_settings_events(
        self,
        user_id: str,
        event_types: list[EventType],
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[DomainUserSettingsChangedEvent]:
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

        docs = await find_query.to_list()
        return [
            DomainUserSettingsChangedEvent.model_validate(e, from_attributes=True).model_copy(
                update={"correlation_id": e.metadata.correlation_id}
            )
            for e in docs
        ]

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
        doc = await UserSettingsSnapshotDocument.find_one({"user_id": user_id})
        if doc:
            await doc.delete()
        await EventDocument.find(EventDocument.aggregate_id == f"user_settings_{user_id}").delete()
        self.logger.info(f"Deleted all settings data for user {user_id}")
