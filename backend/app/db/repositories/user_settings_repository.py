from datetime import datetime
from typing import Any, Dict, List

from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.database_context import Collection, Database
from app.core.logging import logger
from app.domain.enums.events import EventType
from app.domain.events.event_models import CollectionNames
from app.domain.user.settings_models import (
    DomainSettingsEvent,
    DomainUserSettings,
)
from app.infrastructure.mappers import UserSettingsMapper


class UserSettingsRepository:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.snapshots_collection: Collection = self.db.get_collection(CollectionNames.USER_SETTINGS_SNAPSHOTS)
        self.events_collection: Collection = self.db.get_collection(CollectionNames.EVENTS)
        self.mapper = UserSettingsMapper()

    async def create_indexes(self) -> None:
        # Create indexes for settings snapshots
        await self.snapshots_collection.create_indexes(
            [
                IndexModel([("user_id", ASCENDING)], unique=True),
                IndexModel([("updated_at", DESCENDING)]),
            ]
        )

        # Create indexes for settings events
        await self.events_collection.create_indexes(
            [
                IndexModel([("event_type", ASCENDING), ("aggregate_id", ASCENDING)]),
                IndexModel([("aggregate_id", ASCENDING), ("timestamp", ASCENDING)]),
            ]
        )

        logger.info("User settings repository indexes created successfully")

    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        doc = await self.snapshots_collection.find_one({"user_id": user_id})
        if not doc:
            return None
        return self.mapper.from_snapshot_document(doc)

    async def create_snapshot(self, settings: DomainUserSettings) -> None:
        doc = self.mapper.to_snapshot_document(settings)
        await self.snapshots_collection.replace_one({"user_id": settings.user_id}, doc, upsert=True)
        logger.info(f"Created settings snapshot for user {settings.user_id}")

    async def get_settings_events(
        self,
        user_id: str,
        event_types: List[EventType],
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> List[DomainSettingsEvent]:
        query: Dict[str, Any] = {
            "aggregate_id": f"user_settings_{user_id}",
            "event_type": {"$in": [str(et) for et in event_types]},
        }

        if since or until:
            timestamp_query: Dict[str, Any] = {}
            if since:
                timestamp_query["$gt"] = since
            if until:
                timestamp_query["$lte"] = until
            query["timestamp"] = timestamp_query

        cursor = self.events_collection.find(query).sort("timestamp", ASCENDING)

        if limit:
            cursor = cursor.limit(limit)

        docs = await cursor.to_list(None)
        return [self.mapper.event_from_mongo_document(d) for d in docs]

    async def count_events_since_snapshot(self, user_id: str) -> int:
        snapshot = await self.get_snapshot(user_id)

        if not snapshot:
            return await self.events_collection.count_documents({"aggregate_id": f"user_settings_{user_id}"})

        return await self.events_collection.count_documents(
            {"aggregate_id": f"user_settings_{user_id}", "timestamp": {"$gt": snapshot.updated_at}}
        )

    async def count_events_for_user(self, user_id: str) -> int:
        return await self.events_collection.count_documents({"aggregate_id": f"user_settings_{user_id}"})

    async def delete_user_settings(self, user_id: str) -> None:
        """Delete all settings data for a user (snapshot and events)."""
        # Delete snapshot
        await self.snapshots_collection.delete_one({"user_id": user_id})

        # Delete all events
        await self.events_collection.delete_many({"aggregate_id": f"user_settings_{user_id}"})

        logger.info(f"Deleted all settings data for user {user_id}")
