import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

from beanie.odm.enums import SortDirection

from app.db.docs import DLQMessageDocument
from app.dlq import (
    AgeStatistics,
    DLQBatchRetryResult,
    DLQMessage,
    DLQMessageListResult,
    DLQMessageStatus,
    DLQRetryResult,
    DLQStatistics,
    DLQTopicSummary,
    EventTypeStatistic,
    TopicStatistic,
)
from app.dlq.manager import DLQManager
from app.domain.enums.events import EventType
from app.infrastructure.kafka.mappings import get_event_class_for_type


class DLQRepository:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def _doc_to_message(self, doc: DLQMessageDocument) -> DLQMessage:
        event_class = get_event_class_for_type(doc.event_type)
        if not event_class:
            raise ValueError(f"Unknown event type: {doc.event_type}")
        data = doc.model_dump(exclude={"id", "revision_id"})
        return DLQMessage(**{**data, "event": event_class(**data["event"])})

    async def get_dlq_stats(self) -> DLQStatistics:
        # Get counts by status
        status_pipeline: list[Mapping[str, object]] = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
        by_status: Dict[str, int] = {}
        async for doc in DLQMessageDocument.aggregate(status_pipeline):
            if doc["_id"]:
                by_status[doc["_id"]] = doc["count"]

        # Get counts by topic
        topic_pipeline: list[Mapping[str, object]] = [
            {
                "$group": {
                    "_id": "$original_topic",
                    "count": {"$sum": 1},
                    "avg_retry_count": {"$avg": "$retry_count"},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        by_topic: List[TopicStatistic] = []
        async for doc in DLQMessageDocument.aggregate(topic_pipeline):
            by_topic.append(
                TopicStatistic(topic=doc["_id"], count=doc["count"], avg_retry_count=round(doc["avg_retry_count"], 2))
            )

        # Get counts by event type
        event_type_pipeline: list[Mapping[str, object]] = [
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        by_event_type: List[EventTypeStatistic] = []
        async for doc in DLQMessageDocument.aggregate(event_type_pipeline):
            if doc["_id"]:
                by_event_type.append(EventTypeStatistic(event_type=doc["_id"], count=doc["count"]))

        # Get age statistics
        age_pipeline: list[Mapping[str, object]] = [
            {
                "$project": {
                    "age_seconds": {"$divide": [{"$subtract": [datetime.now(timezone.utc), "$failed_at"]}, 1000]}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "min_age": {"$min": "$age_seconds"},
                    "max_age": {"$max": "$age_seconds"},
                    "avg_age": {"$avg": "$age_seconds"},
                }
            },
        ]
        age_result = []
        async for doc in DLQMessageDocument.aggregate(age_pipeline):
            age_result.append(doc)
        age_stats_data = age_result[0] if age_result else {}
        age_stats = AgeStatistics(
            min_age_seconds=age_stats_data.get("min_age", 0.0),
            max_age_seconds=age_stats_data.get("max_age", 0.0),
            avg_age_seconds=age_stats_data.get("avg_age", 0.0),
        )

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
            DLQMessageDocument.event_type == event_type if event_type else None,
        ]
        conditions = [c for c in conditions if c is not None]

        query = DLQMessageDocument.find(*conditions)
        total_count = await query.count()
        docs = await query.sort([("failed_at", SortDirection.DESCENDING)]).skip(offset).limit(limit).to_list()

        return DLQMessageListResult(
            messages=[self._doc_to_message(d) for d in docs],
            total=total_count,
            offset=offset,
            limit=limit,
        )

    async def get_message_by_id(self, event_id: str) -> DLQMessage | None:
        doc = await DLQMessageDocument.find_one({"event_id": event_id})
        return self._doc_to_message(doc) if doc else None

    async def get_topics_summary(self) -> list[DLQTopicSummary]:
        pipeline: list[Mapping[str, object]] = [
            {
                "$group": {
                    "_id": "$original_topic",
                    "count": {"$sum": 1},
                    "statuses": {"$push": "$status"},
                    "oldest_message": {"$min": "$failed_at"},
                    "newest_message": {"$max": "$failed_at"},
                    "avg_retry_count": {"$avg": "$retry_count"},
                    "max_retry_count": {"$max": "$retry_count"},
                }
            },
            {"$sort": {"count": -1}},
        ]

        topics = []
        async for result in DLQMessageDocument.aggregate(pipeline):
            status_counts: dict[str, int] = {}
            for status in result["statuses"]:
                status_counts[status] = status_counts.get(status, 0) + 1

            topics.append(
                DLQTopicSummary(
                    topic=result["_id"],
                    total_messages=result["count"],
                    status_breakdown=status_counts,
                    oldest_message=result["oldest_message"],
                    newest_message=result["newest_message"],
                    avg_retry_count=round(result["avg_retry_count"], 2),
                    max_retry_count=result["max_retry_count"],
                )
            )

        return topics

    async def mark_message_retried(self, event_id: str) -> bool:
        doc = await DLQMessageDocument.find_one({"event_id": event_id})
        if not doc:
            return False
        now = datetime.now(timezone.utc)
        doc.status = DLQMessageStatus.RETRIED
        doc.retried_at = now
        doc.last_updated = now
        await doc.save()
        return True

    async def mark_message_discarded(self, event_id: str, reason: str) -> bool:
        doc = await DLQMessageDocument.find_one({"event_id": event_id})
        if not doc:
            return False
        now = datetime.now(timezone.utc)
        doc.status = DLQMessageStatus.DISCARDED
        doc.discarded_at = now
        doc.discard_reason = reason
        doc.last_updated = now
        await doc.save()
        return True

    async def retry_messages_batch(self, event_ids: list[str], dlq_manager: DLQManager) -> DLQBatchRetryResult:
        details = []
        successful = 0
        failed = 0

        for event_id in event_ids:
            try:
                doc = await DLQMessageDocument.find_one({"event_id": event_id})
                if not doc:
                    failed += 1
                    details.append(DLQRetryResult(event_id=event_id, status="failed", error="Message not found"))
                    continue

                success = await dlq_manager.retry_message_manually(event_id)
                if success:
                    await self.mark_message_retried(event_id)
                    successful += 1
                    details.append(DLQRetryResult(event_id=event_id, status="success"))
                else:
                    failed += 1
                    details.append(DLQRetryResult(event_id=event_id, status="failed", error="Retry failed"))

            except Exception as e:
                self.logger.error(f"Error retrying message {event_id}: {e}")
                failed += 1
                details.append(DLQRetryResult(event_id=event_id, status="failed", error=str(e)))

        return DLQBatchRetryResult(total=len(event_ids), successful=successful, failed=failed, details=details)
