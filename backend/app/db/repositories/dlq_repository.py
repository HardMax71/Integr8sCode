from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.domain.dlq.dlq_models import (
    DLQAgeStats,
    DLQBatchRetryResult,
    DLQEventTypeStats,
    DLQFields,
    DLQMessage,
    DLQMessageFilter,
    DLQMessageListResult,
    DLQMessageStatus,
    DLQRetryResult,
    DLQStatistics,
    DLQStatsByStatus,
    DLQTopicStats,
    DLQTopicSummary,
)


class DLQRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.dlq_collection: AsyncIOMotorCollection = self.db.get_collection("dlq_messages")

    async def get_dlq_stats(self) -> DLQStatistics:
        """Get DLQ statistics."""
        try:
            # Get counts by status
            status_pipeline: List[Mapping[str, Any]] = [
                {"$group": {
                    "_id": f"${DLQFields.STATUS}",
                    "count": {"$sum": 1}
                }}
            ]

            status_results = []
            async for doc in self.dlq_collection.aggregate(status_pipeline):
                status_results.append(doc)
            
            by_status = DLQStatsByStatus.from_aggregation(status_results)

            # Get counts by topic
            topic_pipeline: List[Mapping[str, Any]] = [
                {"$group": {
                    "_id": f"${DLQFields.ORIGINAL_TOPIC}",
                    "count": {"$sum": 1},
                    "avg_retry_count": {"$avg": f"${DLQFields.RETRY_COUNT}"}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]

            by_topic = []
            async for doc in self.dlq_collection.aggregate(topic_pipeline):
                by_topic.append(DLQTopicStats(
                    topic=doc["_id"],
                    count=doc["count"],
                    avg_retry_count=round(doc["avg_retry_count"], 2)
                ))

            # Get counts by event type
            event_type_pipeline: List[Mapping[str, Any]] = [
                {"$group": {
                    "_id": f"${DLQFields.EVENT_TYPE}",
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]

            by_event_type = []
            async for doc in self.dlq_collection.aggregate(event_type_pipeline):
                if doc["_id"]:  # Skip null event types
                    by_event_type.append(DLQEventTypeStats(
                        event_type=doc["_id"],
                        count=doc["count"]
                    ))

            # Get age statistics
            age_pipeline: List[Mapping[str, Any]] = [
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
            age_stats_data = age_result[0] if age_result else None
            age_stats = DLQAgeStats.from_aggregation(age_stats_data)

            return DLQStatistics(
                by_status=by_status,
                by_topic=by_topic,
                by_event_type=by_event_type,
                age_stats=age_stats
            )

        except Exception as e:
            logger.error(f"Error getting DLQ stats: {e}")
            raise

    async def get_messages(
            self,
            status: Optional[str] = None,
            topic: Optional[str] = None,
            event_type: Optional[str] = None,
            limit: int = 50,
            offset: int = 0
    ) -> DLQMessageListResult:
        """Get DLQ messages with filters."""
        try:
            # Create filter
            filter = DLQMessageFilter(
                status=DLQMessageStatus(status) if status else None,
                topic=topic,
                event_type=event_type
            )
            
            query = filter.to_query()
            total_count = await self.dlq_collection.count_documents(query)

            cursor = self.dlq_collection.find(query).sort(
                DLQFields.FAILED_AT, -1
            ).skip(offset).limit(limit)

            messages = []
            async for doc in cursor:
                messages.append(DLQMessage.from_dict(doc))

            return DLQMessageListResult(
                messages=messages,
                total=total_count,
                offset=offset,
                limit=limit
            )

        except Exception as e:
            logger.error(f"Error getting DLQ messages: {e}")
            raise

    async def get_message_by_id(self, event_id: str) -> Optional[DLQMessage]:
        """Get DLQ message by event ID."""
        try:
            doc = await self.dlq_collection.find_one({DLQFields.EVENT_ID: event_id})

            if not doc:
                return None

            return DLQMessage.from_dict(doc)

        except Exception as e:
            logger.error(f"Error getting DLQ message {event_id}: {e}")
            raise

    async def get_message_for_retry(self, event_id: str) -> Optional[DLQMessage]:
        """Get DLQ message for retry operation."""
        try:
            doc = await self.dlq_collection.find_one({DLQFields.EVENT_ID: event_id})

            if not doc:
                return None

            return DLQMessage.from_dict(doc)

        except Exception as e:
            logger.error(f"Error getting message for retry {event_id}: {e}")
            raise

    async def get_topics_summary(self) -> List[DLQTopicSummary]:
        """Get summary of all topics in DLQ."""
        try:
            pipeline: List[Mapping[str, Any]] = [
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
                status_counts: Dict[str, int] = {}
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

        except Exception as e:
            logger.error(f"Error getting DLQ topics summary: {e}")
            raise

    async def mark_message_retried(self, event_id: str) -> bool:
        """Mark a message as retried."""
        try:
            now = datetime.now(timezone.utc)
            result = await self.dlq_collection.update_one(
                {DLQFields.EVENT_ID: event_id},
                {
                    "$set": {
                        DLQFields.STATUS: DLQMessageStatus.RETRIED.value,
                        DLQFields.RETRIED_AT: now,
                        DLQFields.LAST_UPDATED: now
                    }
                }
            )
            return result.modified_count > 0

        except Exception as e:
            logger.error(f"Error marking message as retried {event_id}: {e}")
            raise

    async def mark_message_discarded(self, event_id: str, reason: str) -> bool:
        """Mark a message as discarded."""
        try:
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

        except Exception as e:
            logger.error(f"Error marking message as discarded {event_id}: {e}")
            raise

    async def retry_messages_batch(self, event_ids: List[str], dlq_manager: Any) -> DLQBatchRetryResult:
        """Retry a batch of DLQ messages."""
        details = []
        successful = 0
        failed = 0

        for event_id in event_ids:
            try:
                # Get message from repository
                message = await self.get_message_for_retry(event_id)

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


def get_dlq_repository(request: Request) -> DLQRepository:
    db_manager: DatabaseManager = request.app.state.db_manager
    return DLQRepository(db_manager.get_database())
