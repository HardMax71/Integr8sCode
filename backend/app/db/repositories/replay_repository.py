from typing import Any, AsyncIterator, Dict, List

from pymongo import ASCENDING, DESCENDING

from app.core.database_context import Collection, Database
from app.core.logging import logger
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus
from app.domain.events.event_models import CollectionNames
from app.domain.replay import ReplayFilter, ReplaySessionState
from app.infrastructure.mappers import ReplayStateMapper


class ReplayRepository:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.replay_collection: Collection = database.get_collection(CollectionNames.REPLAY_SESSIONS)
        self.events_collection: Collection = database.get_collection(CollectionNames.EVENTS)
        self._mapper = ReplayStateMapper()

    async def create_indexes(self) -> None:
        # Replay sessions indexes
        await self.replay_collection.create_index([("session_id", ASCENDING)], unique=True)
        await self.replay_collection.create_index([("status", ASCENDING)])
        await self.replay_collection.create_index([("created_at", DESCENDING)])
        await self.replay_collection.create_index([("user_id", ASCENDING)])

        # Events collection indexes for replay queries
        await self.events_collection.create_index([("execution_id", 1), ("timestamp", 1)])
        await self.events_collection.create_index([("event_type", 1), ("timestamp", 1)])
        await self.events_collection.create_index([("metadata.user_id", 1), ("timestamp", 1)])

        logger.info("Replay repository indexes created successfully")

    async def save_session(self, session: ReplaySessionState) -> None:
        """Save or update a replay session (domain → persistence)."""
        doc = self._mapper.to_mongo_document(session)
        await self.replay_collection.update_one({"session_id": session.session_id}, {"$set": doc}, upsert=True)

    async def get_session(self, session_id: str) -> ReplaySessionState | None:
        """Get a replay session by ID (persistence → domain)."""
        data = await self.replay_collection.find_one({"session_id": session_id})
        return self._mapper.from_mongo_document(data) if data else None

    async def list_sessions(
        self, status: ReplayStatus | None = None, user_id: str | None = None, limit: int = 100, skip: int = 0
    ) -> list[ReplaySessionState]:
        collection = self.replay_collection

        query: dict[str, object] = {}
        if status:
            query["status"] = status.value
        if user_id:
            query["config.filter.user_id"] = user_id

        cursor = collection.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit)
        sessions: list[ReplaySessionState] = []
        async for doc in cursor:
            sessions.append(self._mapper.from_mongo_document(doc))
        return sessions

    async def update_session_status(self, session_id: str, status: ReplayStatus) -> bool:
        """Update the status of a replay session"""
        result = await self.replay_collection.update_one({"session_id": session_id}, {"$set": {"status": status.value}})
        return result.modified_count > 0

    async def delete_old_sessions(self, cutoff_time: str) -> int:
        """Delete old completed/failed/cancelled sessions"""
        terminal_statuses = [
            ReplayStatus.COMPLETED.value,
            ReplayStatus.FAILED.value,
            ReplayStatus.CANCELLED.value,
        ]
        result = await self.replay_collection.delete_many(
            {"created_at": {"$lt": cutoff_time}, "status": {"$in": terminal_statuses}}
        )
        return result.deleted_count

    async def count_sessions(self, query: dict[str, object] | None = None) -> int:
        """Count sessions matching the given query"""
        return await self.replay_collection.count_documents(query or {})

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        """Update specific fields of a replay session"""
        if not updates.has_updates():
            return False

        mongo_updates = updates.to_dict()
        result = await self.replay_collection.update_one({"session_id": session_id}, {"$set": mongo_updates})
        return result.modified_count > 0

    async def count_events(self, replay_filter: ReplayFilter) -> int:
        """Count events matching the given filter"""
        query = replay_filter.to_mongo_query()
        return await self.events_collection.count_documents(query)

    async def fetch_events(
        self, replay_filter: ReplayFilter, batch_size: int = 100, skip: int = 0
    ) -> AsyncIterator[List[Dict[str, Any]]]:
        """Fetch events in batches based on filter"""
        query = replay_filter.to_mongo_query()
        cursor = self.events_collection.find(query).sort("timestamp", 1).skip(skip)

        batch = []
        async for doc in cursor:
            batch.append(doc)
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
