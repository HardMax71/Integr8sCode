"""Dead Letter Queue management with retry policies and monitoring"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import Counter, Gauge, Histogram
from app.domain.dlq.dlq_models import (
    DLQFields,
    DLQMessage,
    DLQMessageStatus,
    RetryStrategy,
)
from app.domain.dlq.dlq_models import (
    RetryPolicy as DomainRetryPolicy,
)
from app.domain.events.event_models import Event

# Metrics
DLQ_MESSAGES_RECEIVED = Counter(
    "dlq_messages_received_total",
    "Total number of messages received in DLQ",
    ["original_topic", "event_type"]
)

DLQ_MESSAGES_RETRIED = Counter(
    "dlq_messages_retried_total",
    "Total number of messages retried from DLQ",
    ["original_topic", "event_type", "result"]
)

DLQ_MESSAGES_DISCARDED = Counter(
    "dlq_messages_discarded_total",
    "Total number of messages discarded from DLQ",
    ["original_topic", "event_type", "reason"]
)

DLQ_PROCESSING_DURATION = Histogram(
    "dlq_processing_duration_seconds",
    "Time taken to process DLQ messages",
    ["operation"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
)

DLQ_QUEUE_SIZE = Gauge(
    "dlq_queue_size",
    "Current number of messages in DLQ",
    ["original_topic"]
)

DLQ_AGE_HISTOGRAM = Histogram(
    "dlq_message_age_seconds",
    "Age of messages in DLQ",
    buckets=[60, 300, 900, 3600, 7200, 14400, 86400]  # 1m, 5m, 15m, 1h, 2h, 4h, 24h
)


class RetryPolicy(DomainRetryPolicy):
    """Extended retry policy with additional functionality for DLQ management."""

    def __init__(
            self,
            topic: str,
            strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries: int = 5,
            base_delay_seconds: float = 60.0,
            max_delay_seconds: float = 3600.0,
            retry_multiplier: float = 2.0,
            jitter_factor: float = 0.1,
    ):
        super().__init__(
            topic=topic,
            strategy=strategy,
            max_retries=max_retries,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            retry_multiplier=retry_multiplier
        )
        self.jitter_factor = jitter_factor

    def should_retry(self, message: DLQMessage) -> bool:
        """Check if message should be retried"""
        if self.strategy == RetryStrategy.MANUAL:
            return False

        return message.retry_count < self.max_retries

    def get_next_retry_time(self, message: DLQMessage) -> datetime:
        """Calculate next retry time"""
        if self.strategy == RetryStrategy.IMMEDIATE:
            return datetime.now(timezone.utc)

        elif self.strategy == RetryStrategy.FIXED_INTERVAL:
            delay = self.base_delay_seconds

        elif self.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = min(
                self.base_delay_seconds * (self.retry_multiplier ** message.retry_count),
                self.max_delay_seconds
            )
            # Add jitter
            import random
            jitter = delay * self.jitter_factor * (2 * random.random() - 1)
            delay += jitter

        else:  # SCHEDULED or custom
            delay = self.base_delay_seconds

        return datetime.now(timezone.utc) + timedelta(seconds=delay)


class DLQManager:
    """Manages Dead Letter Queue operations"""

    def __init__(
            self,
            database: Optional[AsyncIOMotorDatabase] = None,
            dlq_topic: str = "dead-letter-queue",
            retry_topic_suffix: str = "-retry",
            default_retry_policy: Optional[RetryPolicy] = None,
    ):
        self.database = database
        self.dlq_topic = dlq_topic
        self.retry_topic_suffix = retry_topic_suffix
        self.default_retry_policy = default_retry_policy or RetryPolicy(
            topic="default",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )

        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None
        self.dlq_collection: Optional[AsyncIOMotorCollection] = None

        self._running = False
        self._process_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

        # Topic-specific retry policies
        self._retry_policies: dict[str, RetryPolicy] = {}

        # Message filters
        self._filters: list[Callable[[DLQMessage], bool]] = []

        # Retry callbacks
        self._callbacks: dict[str, list[Callable]] = {
            "before_retry": [],
            "after_retry": [],
            "on_discard": [],
        }

    async def start(self) -> None:
        """Start DLQ manager"""
        if self._running:
            return

        settings = get_settings()

        # Initialize consumer
        self.consumer = AIOKafkaConsumer(
            self.dlq_topic,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="dlq-manager",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )

        # Initialize producer for retries
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="dlq-manager-producer",
            acks="all",
            enable_idempotence=True,
        )

        await self.consumer.start()
        await self.producer.start()

        # Initialize MongoDB collection
        if self.database is None:
            raise RuntimeError("Database not provided to DLQManager")
        self.dlq_collection = self.database.dlq_messages

        # Create indexes
        await self._create_indexes()

        self._running = True

        # Start processing tasks
        self._process_task = asyncio.create_task(self._process_messages())
        self._monitor_task = asyncio.create_task(self._monitor_dlq())

        logger.info("DLQ Manager started")

    async def stop(self) -> None:
        """Stop DLQ manager"""
        if not self._running:
            return

        self._running = False

        # Cancel tasks
        for task in [self._process_task, self._monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop Kafka clients
        if self.consumer:
            await self.consumer.stop()

        if self.producer:
            await self.producer.stop()

        logger.info("DLQ Manager stopped")

    async def _create_indexes(self) -> None:
        """Create MongoDB indexes for DLQ collection"""
        if self.dlq_collection is None:
            return

        await self.dlq_collection.create_indexes([
            IndexModel([("event_id", ASCENDING)], unique=True),
            IndexModel([("original_topic", ASCENDING)]),
            IndexModel([("event_type", ASCENDING)]),
            IndexModel([("failed_at", DESCENDING)]),
            IndexModel([("retry_count", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("next_retry_at", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=7 * 24 * 3600),  # TTL: 7 days
        ])

    async def _process_messages(self) -> None:
        """Process messages from DLQ"""
        while self._running:
            try:
                # Fetch messages in batches
                if not self.consumer:
                    logger.error("Consumer not initialized")
                    continue

                records = await self.consumer.getmany(timeout_ms=1000, max_records=100)

                for _topic_partition, messages in records.items():
                    for msg in messages:
                        start_time = asyncio.get_event_loop().time()

                        try:
                            # Parse DLQ message
                            dlq_data = json.loads(msg.value.decode('utf-8'))

                            dlq_message = DLQMessage(
                                event=Event.from_dict(dlq_data["event"]),
                                original_topic=dlq_data["original_topic"],
                                error=dlq_data["error"],
                                retry_count=dlq_data["retry_count"],
                                failed_at=datetime.fromisoformat(dlq_data["failed_at"]),
                                producer_id=dlq_data["producer_id"],
                                status=DLQMessageStatus.PENDING,
                                dlq_offset=msg.offset,
                                dlq_partition=msg.partition,
                            )

                            # Update metrics
                            DLQ_MESSAGES_RECEIVED.labels(
                                original_topic=dlq_message.original_topic,
                                event_type=dlq_message.event_type
                            ).inc()

                            DLQ_AGE_HISTOGRAM.observe(dlq_message.age_seconds)

                            # Process message
                            await self._process_dlq_message(dlq_message)

                        except Exception as e:
                            logger.error(f"Error processing DLQ message: {e}")

                        finally:
                            # Record processing time
                            duration = asyncio.get_event_loop().time() - start_time
                            DLQ_PROCESSING_DURATION.labels(operation="process").observe(duration)

                # Commit offsets
                if self.consumer:
                    await self.consumer.commit()

            except Exception as e:
                logger.error(f"Error in DLQ processing loop: {e}")
                await asyncio.sleep(5)

    async def _process_dlq_message(self, message: DLQMessage) -> None:
        """Process individual DLQ message"""
        # Apply filters
        for filter_func in self._filters:
            if not filter_func(message):
                logger.info(f"Message {message.event_id} filtered out")
                return

        # Store in MongoDB
        await self._store_message(message)

        # Get retry policy for topic
        retry_policy = self._retry_policies.get(
            message.original_topic,
            self.default_retry_policy
        )

        # Check if should retry
        if not retry_policy.should_retry(message):
            await self._discard_message(message, "max_retries_exceeded")
            return

        # Calculate next retry time
        next_retry = retry_policy.get_next_retry_time(message)

        # Update message status
        if message.event_id:
            await self._update_message_status(
                message.event_id,
                "scheduled",
                next_retry_at=next_retry
            )

        # If immediate retry, process now
        if retry_policy.strategy == RetryStrategy.IMMEDIATE:
            await self._retry_message(message)

    async def _store_message(self, message: DLQMessage) -> None:
        """Store DLQ message in MongoDB"""
        if self.dlq_collection is None:
            return

        # Ensure message has proper status and timestamps
        message.status = DLQMessageStatus.PENDING
        message.last_updated = datetime.now(timezone.utc)

        doc = message.to_dict()

        await self.dlq_collection.update_one(
            {DLQFields.EVENT_ID: message.event_id},
            {"$set": doc},
            upsert=True
        )

    async def _update_message_status(
            self,
            event_id: str,
            status: str,
            **kwargs: Any
    ) -> None:
        """Update message status in MongoDB"""
        if self.dlq_collection is None:
            return

        update_doc = {
            str(DLQFields.STATUS): status,
            str(DLQFields.LAST_UPDATED): datetime.now(timezone.utc)
        }

        # Add any additional fields
        for key, value in kwargs.items():
            if key == "next_retry_at":
                update_doc[str(DLQFields.NEXT_RETRY_AT)] = value
            else:
                update_doc[key] = value

        await self.dlq_collection.update_one(
            {str(DLQFields.EVENT_ID): event_id},
            {"$set": update_doc}
        )

    async def _retry_message(self, message: DLQMessage) -> None:
        """Retry sending a message to its original topic"""
        # Trigger before_retry callbacks
        await self._trigger_callbacks("before_retry", message)

        try:
            # Recreate event from stored data
            event_data = message.event

            # Send to retry topic first (for monitoring)
            retry_topic = f"{message.original_topic}{self.retry_topic_suffix}"

            # Prepare headers
            headers = [
                ("dlq_retry_count", str(message.retry_count + 1).encode()),
                ("dlq_original_error", message.error.encode()),
                ("dlq_retry_timestamp", datetime.now(timezone.utc).isoformat().encode()),
            ]

            # Send to retry topic
            if not self.producer:
                raise RuntimeError("Producer not initialized")

            if not message.event_id:
                raise ValueError("Message event_id is required")

            await self.producer.send(
                retry_topic,
                value=json.dumps(event_data.to_dict()).encode(),
                key=message.event_id.encode(),
                headers=headers
            )

            # Send to original topic
            await self.producer.send(
                message.original_topic,
                value=json.dumps(event_data.to_dict()).encode(),
                key=message.event_id.encode(),
                headers=headers
            )

            # Update metrics
            DLQ_MESSAGES_RETRIED.labels(
                original_topic=message.original_topic,
                event_type=message.event_type,
                result="success"
            ).inc()

            # Update status
            if message.event_id:
                await self._update_message_status(
                    message.event_id,
                    "retried",
                    retried_at=datetime.now(timezone.utc),
                    retry_count=message.retry_count + 1
                )

            # Trigger after_retry callbacks
            await self._trigger_callbacks("after_retry", message, success=True)

            logger.info(f"Successfully retried message {message.event_id}")

        except Exception as e:
            logger.error(f"Failed to retry message {message.event_id}: {e}")

            # Update metrics
            DLQ_MESSAGES_RETRIED.labels(
                original_topic=message.original_topic,
                event_type=message.event_type,
                result="failure"
            ).inc()

            # Update retry count and reschedule
            message.retry_count += 1
            retry_policy = self._retry_policies.get(
                message.original_topic,
                self.default_retry_policy
            )

            if retry_policy.should_retry(message):
                next_retry = retry_policy.get_next_retry_time(message)
                if message.event_id:
                    await self._update_message_status(
                        message.event_id,
                        "scheduled",
                        next_retry_at=next_retry,
                        retry_count=message.retry_count,
                        last_error=str(e)
                    )
            else:
                await self._discard_message(message, "retry_failed")

            # Trigger after_retry callbacks
            await self._trigger_callbacks("after_retry", message, success=False, error=e)

    async def _discard_message(self, message: DLQMessage, reason: str) -> None:
        """Discard a message from DLQ"""
        # Update metrics
        DLQ_MESSAGES_DISCARDED.labels(
            original_topic=message.original_topic,
            event_type=message.event_type,
            reason=reason
        ).inc()

        # Update status
        if message.event_id:
            await self._update_message_status(
                message.event_id,
                "discarded",
                discarded_at=datetime.now(timezone.utc),
                discard_reason=reason
            )

        # Trigger callbacks
        await self._trigger_callbacks("on_discard", message, reason)

        logger.warning(f"Discarded message {message.event_id} due to {reason}")

    async def _monitor_dlq(self) -> None:
        """Monitor DLQ and process scheduled retries"""
        while self._running:
            try:
                if self.dlq_collection is None:
                    await asyncio.sleep(60)
                    continue

                # Find messages ready for retry
                now = datetime.now(timezone.utc)

                cursor = self.dlq_collection.find({
                    "status": "scheduled",
                    "next_retry_at": {"$lte": now}
                }).limit(100)

                async for doc in cursor:
                    try:
                        # Recreate DLQ message
                        message = DLQMessage(
                            event=Event.from_dict(doc["event"]),
                            original_topic=doc["original_topic"],
                            error=doc["error"],
                            retry_count=doc["retry_count"],
                            failed_at=doc["failed_at"] if isinstance(doc["failed_at"], datetime)
                            else datetime.fromisoformat(doc["failed_at"]),
                            producer_id=doc["producer_id"],
                            status=DLQMessageStatus(doc.get("status", DLQMessageStatus.PENDING)),
                        )

                        # Retry message
                        await self._retry_message(message)

                    except Exception as e:
                        logger.error(f"Error retrying scheduled message: {e}")

                # Update queue size metrics
                await self._update_queue_metrics()

                # Sleep before next check
                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Error in DLQ monitor: {e}")
                await asyncio.sleep(60)

    async def _update_queue_metrics(self) -> None:
        """Update DLQ queue size metrics"""
        if self.dlq_collection is None:
            return

        # Get counts by topic
        pipeline: Sequence[Mapping[str, Any]] = [
            {"$match": {str(DLQFields.STATUS): {"$in": [DLQMessageStatus.PENDING.value,
                                                        DLQMessageStatus.SCHEDULED.value]}}},
            {"$group": {
                "_id": f"${DLQFields.ORIGINAL_TOPIC}",
                "count": {"$sum": 1}
            }}
        ]

        async for result in self.dlq_collection.aggregate(pipeline):
            DLQ_QUEUE_SIZE.labels(
                original_topic=result["_id"]
            ).set(result["count"])

    def set_retry_policy(self, topic: str, policy: RetryPolicy) -> None:
        """Set retry policy for a specific topic"""
        self._retry_policies[topic] = policy

    def add_filter(self, filter_func: Callable[[DLQMessage], bool]) -> None:
        """Add a filter function for DLQ messages"""
        self._filters.append(filter_func)

    def add_callback(self, event_type: str, callback: Callable) -> None:
        """Add callback for DLQ events"""
        if event_type in self._callbacks:
            self._callbacks[event_type].append(callback)

    async def _trigger_callbacks(self, event_type: str, *args: Any, **kwargs: Any) -> None:
        """Trigger callbacks for an event type"""
        for callback in self._callbacks.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in DLQ callback {callback.__name__}: {e}")

    async def retry_message_manually(self, event_id: str) -> bool:
        """Manually retry a specific message"""
        if self.dlq_collection is None:
            return False

        doc = await self.dlq_collection.find_one({"event_id": event_id})
        if not doc:
            logger.error(f"Message {event_id} not found in DLQ")
            return False

        message = DLQMessage(
            event=Event.from_dict(doc["event"]),
            original_topic=doc["original_topic"],
            error=doc["error"],
            retry_count=doc["retry_count"],
            failed_at=doc["failed_at"] if isinstance(doc["failed_at"], datetime)
            else datetime.fromisoformat(doc["failed_at"]),
            producer_id=doc["producer_id"],
            status=DLQMessageStatus(doc.get("status", DLQMessageStatus.PENDING)),
        )

        await self._retry_message(message)
        return True

    async def get_dlq_stats(self) -> dict[str, Any]:
        """Get DLQ statistics"""
        if self.dlq_collection is None:
            return {}

        pipeline = [
            {"$facet": {
                "by_status": [
                    {"$group": {
                        "_id": f"${DLQFields.STATUS}",
                        "count": {"$sum": 1}
                    }}
                ],
                "by_topic": [
                    {"$group": {
                        "_id": f"${DLQFields.ORIGINAL_TOPIC}",
                        "count": {"$sum": 1},
                        "avg_retry_count": {"$avg": f"${DLQFields.RETRY_COUNT}"},
                        "max_retry_count": {"$max": f"${DLQFields.RETRY_COUNT}"}
                    }}
                ],
                "by_event_type": [
                    {"$group": {
                        "_id": f"${DLQFields.EVENT_TYPE}",
                        "count": {"$sum": 1}
                    }}
                ],
                "age_stats": [
                    {"$group": {
                        "_id": None,
                        "oldest_message": {"$min": f"${DLQFields.FAILED_AT}"},
                        "newest_message": {"$max": f"${DLQFields.FAILED_AT}"},
                        "total_count": {"$sum": 1}
                    }}
                ]
            }}
        ]

        result = await self.dlq_collection.aggregate(pipeline).next()

        return {
            "by_status": {item["_id"]: item["count"] for item in result["by_status"]},
            "by_topic": result["by_topic"],
            "by_event_type": result["by_event_type"],
            "age_stats": result["age_stats"][0] if result["age_stats"] else {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


def create_dlq_manager(
    database: AsyncIOMotorDatabase,
    dlq_topic: str = "dead-letter-queue",
    retry_topic_suffix: str = "-retry",
    default_retry_policy: Optional[RetryPolicy] = None,
) -> DLQManager:
    """Factory function to create a DLQ manager.
    
    Args:
        database: MongoDB database instance
        dlq_topic: Kafka topic for dead letter queue
        retry_topic_suffix: Suffix for retry topics
        default_retry_policy: Default retry policy for messages
        
    Returns:
        A new DLQ manager instance
    """
    return DLQManager(
        database=database,
        dlq_topic=dlq_topic,
        retry_topic_suffix=retry_topic_suffix,
        default_retry_policy=default_retry_policy,
    )
