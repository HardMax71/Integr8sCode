import dataclasses
from datetime import datetime

import structlog
from beanie.odm.enums import SortDirection
from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import GT, LTE, Eq, In

from app.db.docs import EventDocument, UserSettingsDocument, UserSettingsSnapshotDocument
from app.domain.enums import EventType
from app.domain.user import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainUserSettings,
    DomainUserSettingsChangedEvent,
)

_settings_fields = set(DomainUserSettings.__dataclass_fields__)
_event_fields = set(DomainUserSettingsChangedEvent.__dataclass_fields__)


class UserSettingsRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    @staticmethod
    def _to_settings(doc: UserSettingsDocument) -> DomainUserSettings:
        data = doc.model_dump(include=_settings_fields)
        if isinstance(data.get("notifications"), dict):
            data["notifications"] = DomainNotificationSettings(**data["notifications"])
        if isinstance(data.get("editor"), dict):
            data["editor"] = DomainEditorSettings(**data["editor"])
        return DomainUserSettings(**data)

    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        doc = await UserSettingsDocument.find_one(UserSettingsDocument.user_id == user_id)
        if not doc:
            return None
        return self._to_settings(doc)

    async def create_snapshot(self, settings: DomainUserSettings) -> None:
        existing = await UserSettingsDocument.find_one(UserSettingsDocument.user_id == settings.user_id)
        doc = UserSettingsDocument(**dataclasses.asdict(settings))
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
        sort_order: SortDirection = SortDirection.ASCENDING,
    ) -> list[DomainUserSettingsChangedEvent]:
        aggregate_id = f"user_settings_{user_id}"
        conditions: list[BaseFindOperator] = [
            Eq(EventDocument.aggregate_id, aggregate_id),
            In(EventDocument.event_type, event_types),
        ]
        if since:
            conditions.append(GT(EventDocument.timestamp, since))
        if until:
            conditions.append(LTE(EventDocument.timestamp, until))

        find_query = EventDocument.find(*conditions).sort([("timestamp", sort_order)])
        if limit:
            find_query = find_query.limit(limit)

        docs = await find_query.to_list()
        return [DomainUserSettingsChangedEvent(**e.model_dump(include=_event_fields)) for e in docs]

    async def count_events_since_snapshot(self, user_id: str) -> int:
        aggregate_id = f"user_settings_{user_id}"
        snapshot = await self.get_snapshot(user_id)
        if not snapshot:
            return await EventDocument.find(EventDocument.aggregate_id == aggregate_id).count()

        return await EventDocument.find(
            EventDocument.aggregate_id == aggregate_id,
            GT(EventDocument.timestamp, snapshot.updated_at),
        ).count()

    async def delete_user_settings(self, user_id: str) -> None:
        doc = await UserSettingsSnapshotDocument.find_one(UserSettingsSnapshotDocument.user_id == user_id)
        if doc:
            await doc.delete()
        await EventDocument.find(EventDocument.aggregate_id == f"user_settings_{user_id}").delete()
        self.logger.info(f"Deleted all settings data for user {user_id}")
