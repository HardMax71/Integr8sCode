import dataclasses
from datetime import datetime, timezone
from typing import Any

import structlog
from beanie.odm.enums import SortDirection
from beanie.operators import Set
from monggregate import Pipeline, S

from app.db.docs import DLQMessageDocument
from app.dlq import (
    DLQMessage,
    DLQMessageListResult,
    DLQMessageStatus,
    DLQMessageUpdate,
    DLQTopicSummary,
)
from app.domain.enums import EventType
from app.domain.events import DomainEventAdapter

_dlq_fields = set(DLQMessage.__dataclass_fields__)


class DLQRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    @staticmethod
    def _to_domain(doc: DLQMessageDocument) -> DLQMessage:
        data = doc.model_dump(include=_dlq_fields)
        data["event"] = DomainEventAdapter.validate_python(data["event"])
        return DLQMessage(**data)

    async def get_messages(
            self,
            status: DLQMessageStatus | None = None,
            topic: str | None = None,
            event_type: EventType | None = None,
            limit: int = 50,
            offset: int = 0,
    ) -> DLQMessageListResult:
        conditions: list[Any] = [
            DLQMessageDocument.status == status if status else None,
            DLQMessageDocument.original_topic == topic if topic else None,
            DLQMessageDocument.event.event_type == event_type if event_type else None,
        ]
        conditions = [c for c in conditions if c is not None]

        query = DLQMessageDocument.find(*conditions)
        total_count = await query.count()
        docs = await query.sort([("failed_at", SortDirection.DESCENDING)]).skip(offset).limit(limit).to_list()

        return DLQMessageListResult(
            messages=[self._to_domain(d) for d in docs],
            total=total_count,
            offset=offset,
            limit=limit,
        )

    async def get_message_by_id(self, event_id: str) -> DLQMessage | None:
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        return self._to_domain(doc) if doc else None

    async def get_topics_summary(self) -> list[DLQTopicSummary]:
        # Two-stage aggregation: group by topic+status first, then by topic with $arrayToObject
        # Note: compound keys need S.field() wrapper for monggregate to add $ prefix
        pipeline = (
            Pipeline()
            .group(
                by={"topic": S.field(DLQMessageDocument.original_topic), "status": S.field(DLQMessageDocument.status)},
                query={
                    "count": S.sum(1),
                    "oldest": S.min(S.field(DLQMessageDocument.failed_at)),
                    "newest": S.max(S.field(DLQMessageDocument.failed_at)),
                    "sum_retry": S.sum(S.field(DLQMessageDocument.retry_count)),
                    "max_retry": S.max(S.field(DLQMessageDocument.retry_count)),
                },
            )
            .group(
                by="$_id.topic",
                query={
                    "status_pairs": S.push({"k": "$_id.status", "v": "$count"}),
                    "total_messages": S.sum("$count"),
                    "oldest_message": S.min("$oldest"),
                    "newest_message": S.max("$newest"),
                    "total_retry": S.sum("$sum_retry"),
                    "doc_count": S.sum("$count"),
                    "max_retry_count": S.max("$max_retry"),
                },
            )
            .sort(by="total_messages", descending=True)
            .project(
                _id=0,
                topic="$_id",
                total_messages=1,
                status_breakdown={"$arrayToObject": "$status_pairs"},
                oldest_message=1,
                newest_message=1,
                avg_retry_count={"$round": [{"$divide": ["$total_retry", "$doc_count"]}, 2]},
                max_retry_count=1,
            )
        )
        results = await DLQMessageDocument.aggregate(pipeline.export()).to_list()
        return [
            DLQTopicSummary(
                topic=r["topic"],
                total_messages=r["total_messages"],
                status_breakdown={DLQMessageStatus(k): v for k, v in r["status_breakdown"].items()},
                oldest_message=r["oldest_message"],
                newest_message=r["newest_message"],
                avg_retry_count=r["avg_retry_count"],
                max_retry_count=r["max_retry_count"],
            )
            for r in results
        ]

    async def save_message(self, message: DLQMessage) -> None:
        """Upsert a DLQ message by event_id (atomic, no TOCTOU race)."""
        payload = dataclasses.asdict(message)
        payload["event"] = message.event.model_dump()
        await DLQMessageDocument.find_one({"event.event_id": message.event.event_id}).upsert(
            Set(payload),  # type: ignore[no-untyped-call]
            on_insert=DLQMessageDocument(**payload),
        )

    async def update_status(self, event_id: str, update: DLQMessageUpdate) -> None:
        """Apply a status update to a DLQ message."""
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            return

        update_dict: dict[str, Any] = {"status": update.status, "last_updated": datetime.now(timezone.utc)}
        if update.next_retry_at is not None:
            update_dict["next_retry_at"] = update.next_retry_at
        if update.retried_at is not None:
            update_dict["retried_at"] = update.retried_at
        if update.discarded_at is not None:
            update_dict["discarded_at"] = update.discarded_at
        if update.retry_count is not None:
            update_dict["retry_count"] = update.retry_count
        if update.discard_reason is not None:
            update_dict["discard_reason"] = update.discard_reason
        if update.last_error is not None:
            update_dict["last_error"] = update.last_error

        await doc.set(update_dict)

    async def find_due_retries(self, limit: int = 100) -> list[DLQMessage]:
        """Find scheduled messages whose retry time has arrived."""
        now = datetime.now(timezone.utc)
        docs = (
            await DLQMessageDocument.find(
                {
                    "status": DLQMessageStatus.SCHEDULED,
                    "next_retry_at": {"$lte": now},
                }
            )
            .limit(limit)
            .to_list()
        )
        return [self._to_domain(doc) for doc in docs]

    async def get_queue_sizes_by_topic(self) -> dict[str, int]:
        """Get message counts per topic for active (pending/scheduled) messages."""
        pipeline: list[dict[str, Any]] = [
            {"$match": {"status": {"$in": [DLQMessageStatus.PENDING, DLQMessageStatus.SCHEDULED]}}},
            {"$group": {"_id": "$original_topic", "count": {"$sum": 1}}},
        ]
        result: dict[str, int] = {}
        async for row in DLQMessageDocument.aggregate(pipeline):
            result[row["_id"]] = row["count"]
        return result
