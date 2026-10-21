from collections.abc import AsyncIterator
from typing import Any

import structlog
from beanie.odm.enums import SortDirection

from app.db.docs import EventDocument, ReplaySessionDocument
from app.domain.enums import ReplayStatus
from app.domain.replay import ReplayFilter


class ReplayRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def create_session(self, session: ReplaySessionDocument) -> None:
        await session.insert()

    async def get_oldest_scheduled_session(self) -> ReplaySessionDocument | None:
        return (
            await ReplaySessionDocument.find(ReplaySessionDocument.status == ReplayStatus.SCHEDULED)
            .sort([("created_at", SortDirection.ASCENDING)])
            .first_or_none()
        )

    async def get_running_sessions(self) -> list[ReplaySessionDocument]:
        return await ReplaySessionDocument.find(ReplaySessionDocument.status == ReplayStatus.RUNNING).to_list()

    async def save_session(self, session: ReplaySessionDocument) -> None:
        await session.save_changes()

    async def count_by_status(self) -> dict[ReplayStatus, int]:
        rows = await ReplaySessionDocument.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list()
        return {ReplayStatus(row["_id"]): row["n"] for row in rows}

    async def fetch_events(self, replay_filter: ReplayFilter, batch_size: int) -> AsyncIterator[list[dict[str, Any]]]:
        query = replay_filter.to_mongo_query()
        cursor = EventDocument.find(query).sort([("timestamp", SortDirection.ASCENDING)])

        batch = []
        async for doc in cursor:
            batch.append(doc.model_dump(exclude={"id", "revision_id", "stored_at", "ttl_expires_at"}))
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
