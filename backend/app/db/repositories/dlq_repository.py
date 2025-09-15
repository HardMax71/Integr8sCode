from datetime import datetime, timezone
from typing import Dict, List, Mapping

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.dlq import (
    AgeStatistics,
    DLQBatchRetryResult,
    DLQFields,
    DLQMessage,
    DLQMessageFilter,
    DLQMessageListResult,
    DLQMessageStatus,
    DLQRetryResult,
    DLQStatistics,
    DLQTopicSummary,
    EventTypeStatistic,
    TopicStatistic,
)
from app.dlq.manager import DLQManager
from app.domain.events.event_models import CollectionNames
from app.infrastructure.mappers.dlq_mapper import DLQMapper


class DLQRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.dlq_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.DLQ_MESSAGES)

    async def get_dlq_stats(self) -> DLQStatistics:
        # Get counts by status
        status_pipeline: list[Mapping[str, object]] = [
            {"$group": {
                "_id": f"${DLQFields.STATUS}",
                "count": {"$sum": 1}
            }}
        ]

        status_results = []
        async for doc in self.dlq_collection.aggregate(status_pipeline):
            status_results.append(doc)

        # Convert status results to dict
        by_status: Dict[str, int] = {}
        for doc in status_results:
            if doc["_id"]:
                by_status[doc["_id"]] = doc["count"]

        # Get counts by topic
        topic_pipeline: list[Mapping[str, object]] = [
            {"$group": {
                "_id": f"${DLQFields.ORIGINAL_TOPIC}",
                "count": {"$sum": 1},
                "avg_retry_count": {"$avg": f"${DLQFields.RETRY_COUNT}"}
            }},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]

        by_topic: List[TopicStatistic] = []
        async for doc in self.dlq_collection.aggregate(topic_pipeline):
            by_topic.append(TopicStatistic(
                topic=doc["_id"],
                count=doc["count"],
                avg_retry_count=round(doc["avg_retry_count"], 2)
            ))

        # Get counts by event type
        event_type_pipeline: list[Mapping[str, object]] = [
            {"$group": {
                "_id": f"${DLQFields.EVENT_TYPE}",
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]

        by_event_type: List[EventTypeStatistic] = []
        async for doc in self.dlq_collection.aggregate(event_type_pipeline):
            if doc["_id"]:  # Skip null event types
                by_event_type.append(EventTypeStatistic(
                    event_type=doc["_id"],
                    count=doc["count"]
                ))

        # Get age statistics
        age_pipeline: list[Mapping[str, object]] = [
            {"$project": {
                "age_seconds": {
                    "$divide": [
                        {"$subtract": [datetime.now(timezone.utc), f"${DLQFields.FAILED_AT}"]},
                        1000
                    ]
                }
            }},
            {"$group": {
                "_id": None,
                "min_age": {"$min": "$age_seconds"},
                "max_age": {"$max": "$age_seconds"},
                "avg_age": {"$avg": "$age_seconds"}
            }}
        ]

        age_result = await self.dlq_collection.aggregate(age_pipeline).to_list(1)
        age_stats_data = age_result[0] if age_result else {}
        age_stats = AgeStatistics(
            min_age_seconds=age_stats_data.get("min_age", 0.0),
            max_age_seconds=age_stats_data.get("max_age", 0.0),
            avg_age_seconds=age_stats_data.get("avg_age", 0.0)
        )

        return DLQStatistics(
            by_status=by_status,
            by_topic=by_topic,
            by_event_type=by_event_type,
            age_stats=age_stats
        )

    async def get_messages(
            self,
            status: str | None = None,
            topic: str | None = None,
            event_type: str | None = None,
            limit: int = 50,
            offset: int = 0
    ) -> DLQMessageListResult:
        # Create filter
        filter = DLQMessageFilter(
            status=DLQMessageStatus(status) if status else None,
            topic=topic,
            event_type=event_type
        )

        query = DLQMapper.filter_to_query(filter)
        total_count = await self.dlq_collection.count_documents(query)

        cursor = self.dlq_collection.find(query).sort(
            DLQFields.FAILED_AT, -1
        ).skip(offset).limit(limit)

        messages = []
        async for doc in cursor:
            messages.append(DLQMapper.from_mongo_document(doc))

        return DLQMessageListResult(
            messages=messages,
            total=total_count,
            offset=offset,
            limit=limit
        )

    async def get_message_by_id(self, event_id: str) -> DLQMessage | None:
        doc = await self.dlq_collection.find_one({DLQFields.EVENT_ID: event_id})
        if not doc:
            return None

        return DLQMapper.from_mongo_document(doc)

    async def get_topics_summary(self) -> list[DLQTopicSummary]:
        pipeline: list[Mapping[str, object]] = [
            {"$group": {
                "_id": f"${DLQFields.ORIGINAL_TOPIC}",
                "count": {"$sum": 1},
                "statuses": {"$push": f"${DLQFields.STATUS}"},
                "oldest_message": {"$min": f"${DLQFields.FAILED_AT}"},
                "newest_message": {"$max": f"${DLQFields.FAILED_AT}"},
                "avg_retry_count": {"$avg": f"${DLQFields.RETRY_COUNT}"},
                "max_retry_count": {"$max": f"${DLQFields.RETRY_COUNT}"}
            }},
            {"$sort": {"count": -1}}
        ]

        topics = []
        async for result in self.dlq_collection.aggregate(pipeline):
            status_counts: dict[str, int] = {}
            for status in result["statuses"]:
                status_counts[status] = status_counts.get(status, 0) + 1

            topics.append(DLQTopicSummary(
                topic=result["_id"],
                total_messages=result["count"],
                status_breakdown=status_counts,
                oldest_message=result["oldest_message"],
                newest_message=result["newest_message"],
                avg_retry_count=round(result["avg_retry_count"], 2),
                max_retry_count=result["max_retry_count"]
            ))

        return topics

    async def mark_message_retried(self, event_id: str) -> bool:
        now = datetime.now(timezone.utc)
        result = await self.dlq_collection.update_one(
            {DLQFields.EVENT_ID: event_id},
            {
                "$set": {
                    DLQFields.STATUS: DLQMessageStatus.RETRIED,
                    DLQFields.RETRIED_AT: now,
                    DLQFields.LAST_UPDATED: now
                }
            }
        )
        return result.modified_count > 0

    async def mark_message_discarded(self, event_id: str, reason: str) -> bool:
        now = datetime.now(timezone.utc)
        result = await self.dlq_collection.update_one(
            {DLQFields.EVENT_ID: event_id},
            {
                "$set": {
                    DLQFields.STATUS: DLQMessageStatus.DISCARDED.value,
                    DLQFields.DISCARDED_AT: now,
                    DLQFields.DISCARD_REASON: reason,
                    DLQFields.LAST_UPDATED: now
                }
            }
        )
        return result.modified_count > 0

    async def retry_messages_batch(self, event_ids: list[str], dlq_manager: DLQManager) -> DLQBatchRetryResult:
        """Retry a batch of DLQ messages."""
        details = []
        successful = 0
        failed = 0

        for event_id in event_ids:
            try:
                # Get message from repository
                message = await self.get_message_by_id(event_id)

                if not message:
                    failed += 1
                    details.append(DLQRetryResult(
                        event_id=event_id,
                        status="failed",
                        error="Message not found"
                    ))
                    continue

                # Use dlq_manager for retry logic
                success = await dlq_manager.retry_message_manually(event_id)

                if success:
                    # Mark as retried
                    await self.mark_message_retried(event_id)
                    successful += 1
                    details.append(DLQRetryResult(
                        event_id=event_id,
                        status="success"
                    ))
                else:
                    failed += 1
                    details.append(DLQRetryResult(
                        event_id=event_id,
                        status="failed",
                        error="Retry failed"
                    ))

            except Exception as e:
                logger.error(f"Error retrying message {event_id}: {e}")
                failed += 1
                details.append(DLQRetryResult(
                    event_id=event_id,
                    status="failed",
                    error=str(e)
                ))

        return DLQBatchRetryResult(
            total=len(event_ids),
            successful=successful,
            failed=failed,
            details=details
        )
