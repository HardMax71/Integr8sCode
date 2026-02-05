import logging
from datetime import datetime, timezone
from typing import Any

from beanie.odm.enums import SortDirection
from beanie.operators import Set
from monggregate import Pipeline, S

from app.db.docs import DLQMessageDocument
from app.dlq import (
    AgeStatistics,
    DLQMessage,
    DLQMessageListResult,
    DLQMessageStatus,
    DLQMessageUpdate,
    DLQStatistics,
    DLQTopicSummary,
    EventTypeStatistic,
    TopicStatistic,
)
from app.domain.enums.events import EventType


class DLQRepository:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    async def get_dlq_stats(self) -> DLQStatistics:
        # Counts by status
        status_pipeline = Pipeline().group(by=S.field(DLQMessageDocument.status), query={"count": S.sum(1)})
        status_results = await DLQMessageDocument.aggregate(status_pipeline.export()).to_list()
        by_status = {doc["_id"]: doc["count"] for doc in status_results if doc["_id"]}

        # Counts by topic (top 10) - project renames _id->topic and rounds avg_retry_count
        topic_pipeline = (
            Pipeline()
            .group(
                by=S.field(DLQMessageDocument.original_topic),
                query={"count": S.sum(1), "avg_retry_count": S.avg(S.field(DLQMessageDocument.retry_count))},
            )
            .sort(by="count", descending=True)
            .limit(10)
            .project(_id=0, topic="$_id", count=1, avg_retry_count={"$round": ["$avg_retry_count", 2]})
        )
        topic_results = await DLQMessageDocument.aggregate(topic_pipeline.export()).to_list()
        by_topic = [TopicStatistic.model_validate(doc) for doc in topic_results]

        # Counts by event type (top 10) - project renames _id->event_type
        event_type_pipeline = (
            Pipeline()
            .group(by=S.field(DLQMessageDocument.event.event_type), query={"count": S.sum(1)})
            .sort(by="count", descending=True)
            .limit(10)
            .project(_id=0, event_type="$_id", count=1)
        )
        event_type_results = await DLQMessageDocument.aggregate(event_type_pipeline.export()).to_list()
        by_event_type = [EventTypeStatistic.model_validate(doc) for doc in event_type_results if doc["event_type"]]

        # Age statistics - use $toLong to convert Date to milliseconds for $avg
        time_pipeline = Pipeline().group(
            by=None,
            query={
                "oldest": S.min(S.field(DLQMessageDocument.failed_at)),
                "newest": S.max(S.field(DLQMessageDocument.failed_at)),
                "avg_failed_at_ms": {"$avg": {"$toLong": S.field(DLQMessageDocument.failed_at)}},
            },
        )
        time_results = await DLQMessageDocument.aggregate(time_pipeline.export()).to_list()
        now = datetime.now(timezone.utc)
        if time_results and time_results[0].get("oldest"):
            r = time_results[0]
            oldest, newest = r["oldest"], r["newest"]
            # MongoDB returns naive datetimes (implicitly UTC), make them aware
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=timezone.utc)
            # Convert average timestamp (ms) back to datetime for age calculation
            avg_failed_at_ms = r.get("avg_failed_at_ms")
            if avg_failed_at_ms:
                avg_failed_at = datetime.fromtimestamp(avg_failed_at_ms / 1000, tz=timezone.utc)
                avg_age_seconds = (now - avg_failed_at).total_seconds()
            else:
                avg_age_seconds = 0.0
            age_stats = AgeStatistics(
                min_age_seconds=(now - newest).total_seconds(),
                max_age_seconds=(now - oldest).total_seconds(),
                avg_age_seconds=avg_age_seconds,
            )
        else:
            age_stats = AgeStatistics()

        return DLQStatistics(by_status=by_status, by_topic=by_topic, by_event_type=by_event_type, age_stats=age_stats)

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
            messages=[DLQMessage.model_validate(d, from_attributes=True) for d in docs],
            total=total_count,
            offset=offset,
            limit=limit,
        )

    async def get_message_by_id(self, event_id: str) -> DLQMessage | None:
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        return DLQMessage.model_validate(doc, from_attributes=True) if doc else None

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
        return [DLQTopicSummary.model_validate(r) for r in results]

    async def save_message(self, message: DLQMessage) -> None:
        """Upsert a DLQ message by event_id (atomic, no TOCTOU race)."""
        payload = message.model_dump()
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
        return [DLQMessage.model_validate(doc, from_attributes=True) for doc in docs]

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

    async def mark_message_retried(self, event_id: str) -> bool:
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            return False
        now = datetime.now(timezone.utc)
        doc.status = DLQMessageStatus.RETRIED
        doc.retried_at = now
        doc.last_updated = now
        await doc.save()
        return True

    async def mark_message_discarded(self, event_id: str, reason: str) -> bool:
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            return False
        now = datetime.now(timezone.utc)
        doc.status = DLQMessageStatus.DISCARDED
        doc.discarded_at = now
        doc.discard_reason = reason
        doc.last_updated = now
        await doc.save()
        return True
