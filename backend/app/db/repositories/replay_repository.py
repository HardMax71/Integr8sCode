import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

from beanie.operators import In, LT

from pymongo import ASCENDING, DESCENDING

from app.db.docs import ReplaySessionDocument, EventDocument, ReplayFilter
from app.domain.enums.replay import ReplayStatus


class ReplayRepository:

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def save_session(self, session: ReplaySessionDocument) -> None:
        existing = await ReplaySessionDocument.find_one({"session_id": session.session_id})
        if existing:
            session.id = existing.id
        await session.save()

    async def get_session(self, session_id: str) -> ReplaySessionDocument | None:
        return await ReplaySessionDocument.find_one({"session_id": session_id})

    async def list_sessions(
        self, status: ReplayStatus | None = None, user_id: str | None = None, limit: int = 100, skip: int = 0
    ) -> list[ReplaySessionDocument]:
        conditions = [
            ReplaySessionDocument.status == status if status else None,
            ReplaySessionDocument.config.filter.user_id == user_id if user_id else None,
        ]
        conditions = [c for c in conditions if c is not None]
        return await ReplaySessionDocument.find(*conditions).sort([("created_at", DESCENDING)]).skip(skip).limit(limit).to_list()

    async def update_session_status(self, session_id: str, status: ReplayStatus) -> bool:
        doc = await self.get_session(session_id)
        if not doc:
            return False
        doc.status = status
        await doc.save()
        return True

    async def delete_old_sessions(self, cutoff_time: datetime) -> int:
        terminal_statuses = [
            ReplayStatus.COMPLETED,
            ReplayStatus.FAILED,
            ReplayStatus.CANCELLED,
        ]
        result = await ReplaySessionDocument.find(
            LT(ReplaySessionDocument.created_at, cutoff_time),
            In(ReplaySessionDocument.status, terminal_statuses),
        ).delete()
        return result.deleted_count

    async def count_sessions(self, *conditions: Any) -> int:
        return await ReplaySessionDocument.find(*conditions).count()

    async def update_replay_session(self, session_id: str, updates: dict) -> bool:
        doc = await self.get_session(session_id)
        if not doc:
            return False
        await doc.set(updates)
        return True

    async def count_events(self, replay_filter: ReplayFilter) -> int:
        query = replay_filter.to_mongo_query()
        return await EventDocument.find(query).count()

    async def fetch_events(
        self, replay_filter: ReplayFilter, batch_size: int = 100, skip: int = 0
    ) -> AsyncIterator[List[Dict[str, Any]]]:
        query = replay_filter.to_mongo_query()
        cursor = EventDocument.find(query).sort([("timestamp", ASCENDING)]).skip(skip)

        batch = []
        async for doc in cursor:
            batch.append(doc.model_dump())
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
