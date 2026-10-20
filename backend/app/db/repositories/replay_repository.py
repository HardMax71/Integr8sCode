from datetime import datetime
from typing import Any, AsyncIterator

import structlog
from beanie.odm.enums import SortDirection
from beanie.operators import LT, In

from app.db.docs import EventDocument, ReplaySessionDocument
from app.domain.enums import REPLAY_TERMINAL, ReplayStatus
from app.domain.replay import ReplayFilter, ReplaySessionChanges


class ReplayRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def create_session(self, session: ReplaySessionDocument) -> None:
        await session.insert()

    async def get_session(self, session_id: str) -> ReplaySessionDocument | None:
        return await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)

    async def list_sessions(
        self, status: ReplayStatus | None = None, user_id: str | None = None, limit: int = 100, skip: int = 0
    ) -> list[ReplaySessionDocument]:
        conditions: list[Any] = [
            ReplaySessionDocument.status == status if status else None,
            ReplaySessionDocument.config.filter.user_id == user_id if user_id else None,
        ]
        conditions = [c for c in conditions if c is not None]
        return (
            await ReplaySessionDocument.find(*conditions)
            .sort([("created_at", SortDirection.DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def update_session_status(self, session_id: str, status: ReplayStatus) -> bool:
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return False
        doc.status = status
        await doc.save()
        return True

    async def delete_old_sessions(self, cutoff_time: datetime) -> int:
        result = await ReplaySessionDocument.find(
            LT(ReplaySessionDocument.created_at, cutoff_time),
            In(ReplaySessionDocument.status, list(REPLAY_TERMINAL)),
        ).delete()
        return result.deleted_count if result else 0

    async def update_replay_session(self, session_id: str, changes: ReplaySessionChanges) -> bool:
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return False
        await doc.update({"$set": changes})
        return True

    async def count_events(self, replay_filter: ReplayFilter) -> int:
        query = replay_filter.to_mongo_query()
        return await EventDocument.find(query).count()

    async def fetch_events(
        self, replay_filter: ReplayFilter, batch_size: int = 100, skip: int = 0
    ) -> AsyncIterator[list[dict[str, Any]]]:
        query = replay_filter.to_mongo_query()
        cursor = EventDocument.find(query).sort([("timestamp", SortDirection.ASCENDING)]).skip(skip)

        batch = []
        async for doc in cursor:
            batch.append(doc.model_dump(exclude={"id", "revision_id", "stored_at", "ttl_expires_at"}))
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
