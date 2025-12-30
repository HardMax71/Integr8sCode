import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any, AsyncIterator

from beanie.odm.enums import SortDirection
from beanie.operators import LT, In

from app.db.docs import EventStoreDocument, ReplaySessionDocument
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus
from app.domain.replay.models import ReplayConfig, ReplayFilter, ReplaySessionState


class ReplayRepository:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def save_session(self, session: ReplaySessionState) -> None:
        existing = await ReplaySessionDocument.find_one({"session_id": session.session_id})
        data = asdict(session)
        # config is a Pydantic model, convert to dict for document
        data["config"] = session.config.model_dump()
        doc = ReplaySessionDocument(**data)
        if existing:
            doc.id = existing.id
        await doc.save()

    async def get_session(self, session_id: str) -> ReplaySessionState | None:
        doc = await ReplaySessionDocument.find_one({"session_id": session_id})
        if not doc:
            return None
        data = doc.model_dump(exclude={"id", "revision_id"})
        data["config"] = ReplayConfig.model_validate(data["config"])
        return ReplaySessionState(**data)

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
        results = []
        for doc in docs:
            data = doc.model_dump(exclude={"id", "revision_id"})
            data["config"] = ReplayConfig.model_validate(data["config"])
            results.append(ReplaySessionState(**data))
        return results

    async def update_session_status(self, session_id: str, status: ReplayStatus) -> bool:
        doc = await ReplaySessionDocument.find_one({"session_id": session_id})
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

    async def count_sessions(self, *conditions: Any) -> int:
        return await ReplaySessionDocument.find(*conditions).count()

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        update_dict = {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(updates).items() if v is not None}
        if not update_dict:
            return False
        doc = await ReplaySessionDocument.find_one({"session_id": session_id})
        if not doc:
            return False
        await doc.set(update_dict)
        return True

    async def count_events(self, replay_filter: ReplayFilter) -> int:
        query = replay_filter.to_mongo_query()
        return await EventStoreDocument.find(query).count()

    async def fetch_events(
        self, replay_filter: ReplayFilter, batch_size: int = 100, skip: int = 0
    ) -> AsyncIterator[list[dict[str, Any]]]:
        query = replay_filter.to_mongo_query()
        cursor = EventStoreDocument.find(query).sort([("timestamp", SortDirection.ASCENDING)]).skip(skip)

        batch = []
        async for doc in cursor:
            batch.append(doc.model_dump(exclude={"id", "revision_id", "stored_at"}))
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
