import logging
from datetime import datetime
from typing import Any, AsyncIterator

from beanie.odm.enums import SortDirection
from beanie.operators import LT, In

from app.db.docs import EventDocument, ReplaySessionDocument
from app.domain.admin import ReplaySessionUpdate
from app.domain.enums import ReplayStatus
from app.domain.replay import ReplayFilter, ReplaySessionState


class ReplayRepository:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def save_session(self, session: ReplaySessionState) -> None:
        existing = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session.session_id)
        doc = ReplaySessionDocument(**session.model_dump())
        if existing:
            doc.id = existing.id
        await doc.save()

    async def get_session(self, session_id: str) -> ReplaySessionState | None:
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return None
        return ReplaySessionState.model_validate(doc, from_attributes=True)

    async def list_sessions(
        self, status: ReplayStatus | None = None, user_id: str | None = None, limit: int = 100, skip: int = 0
    ) -> list[ReplaySessionState]:
        conditions: list[Any] = [
            ReplaySessionDocument.status == status if status else None,
            ReplaySessionDocument.config.filter.user_id == user_id if user_id else None,
        ]
        conditions = [c for c in conditions if c is not None]
        docs = (
            await ReplaySessionDocument.find(*conditions)
            .sort([("created_at", SortDirection.DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        return [ReplaySessionState.model_validate(doc, from_attributes=True) for doc in docs]

    async def update_session_status(self, session_id: str, status: ReplayStatus) -> bool:
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
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
        return result.deleted_count if result else 0

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        update_dict = updates.model_dump(exclude_none=True)
        if not update_dict:
            return False
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return False
        await doc.set(update_dict)
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
