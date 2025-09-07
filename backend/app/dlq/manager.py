import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence

from confluent_kafka import Consumer, KafkaError, Producer
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.core.metrics.context import get_dlq_metrics
from app.dlq.models import (
    DLQFields,
    DLQMessage,
    DLQMessageStatus,
    RetryPolicy,
    RetryStrategy,
)
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import get_settings


class DLQManager:
    def __init__(
            self,
            database: AsyncIOMotorDatabase,
            dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
            retry_topic_suffix: str = "-retry",
            default_retry_policy: RetryPolicy | None = None,
    ):
        self.database = database
        self.metrics = get_dlq_metrics()
        self.dlq_topic = dlq_topic
        self.retry_topic_suffix = retry_topic_suffix
        self.default_retry_policy = default_retry_policy or RetryPolicy(
            topic="default",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )

        self.consumer: Consumer | None = None
        self.producer: Producer | None = None
        self.dlq_collection: AsyncIOMotorCollection[Any] = database.dlq_messages

        self._running = False
        self._process_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None

        # Topic-specific retry policies
        self._retry_policies: dict[str, RetryPolicy] = {}

        # Message filters
        self._filters: list[Callable[[DLQMessage], bool]] = []

        # Retry callbacks - all must be async
        self._callbacks: dict[str, list[Callable[..., Awaitable[None]]]] = {
            "before_retry": [],
            "after_retry": [],
            "on_discard": [],
        }

    async def start(self) -> None:
        """Start DLQ manager"""
        if self._running:
            return

        if self.database is None:
            raise RuntimeError("Database not provided to DLQManager")

        settings = get_settings()

        # Initialize consumer
        self.consumer = Consumer({
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': GroupId.DLQ_MANAGER,
            'enable.auto.commit': False,
            'auto.offset.reset': 'earliest',
            'client.id': 'dlq-manager-consumer'
        })
        self.consumer.subscribe([self.dlq_topic])

        # Initialize producer for retries
        self.producer = Producer({
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'client.id': 'dlq-manager-producer',
            'acks': 'all',
            'enable.idempotence': True,
            'compression.type': 'gzip',
            'batch.size': 16384,
            'linger.ms': 10
        })

        # Indexes ensured by SchemaManager at startup

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
            self.consumer.close()

        if self.producer:
            self.producer.flush(10)  # Wait up to 10 seconds for pending messages

        logger.info("DLQ Manager stopped")

    # Index creation handled by SchemaManager

    async def _process_messages(self) -> None:
        while self._running:
            try:
                # Fetch messages using confluent-kafka poll
                if not self.consumer:
                    logger.error("Consumer not initialized")
                    continue

                # Poll for messages (non-blocking with asyncio)
                msg = await asyncio.to_thread(self.consumer.poll, timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    error = msg.error()
                    if error and error.code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error(f"Consumer error: {error}")
                    continue

                start_time = asyncio.get_event_loop().time()

                schema_registry = SchemaRegistryManager()
                dlq_message = DLQMessage.from_kafka_message(msg, schema_registry)

                # Update metrics
                self.metrics.record_dlq_message_received(
                    dlq_message.original_topic,
                    dlq_message.event_type
                )

                self.metrics.record_dlq_message_age(dlq_message.age_seconds)

                # Process message
                await self._process_dlq_message(dlq_message)

                # Commit offset after successful processing
                await asyncio.to_thread(self.consumer.commit, asynchronous=False)

                # Record processing time
                duration = asyncio.get_event_loop().time() - start_time
                self.metrics.record_dlq_processing_duration(duration, "process")

            except Exception as e:
                logger.error(f"Error in DLQ processing loop: {e}")
                await asyncio.sleep(5)

    async def _process_dlq_message(self, message: DLQMessage) -> None:
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
                DLQMessageStatus.SCHEDULED,
                next_retry_at=next_retry
            )

        # If immediate retry, process now
        if retry_policy.strategy == RetryStrategy.IMMEDIATE:
            await self._retry_message(message)

    async def _store_message(self, message: DLQMessage) -> None:
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
            status: DLQMessageStatus,
            **kwargs: Any
    ) -> None:
        update_doc = {
            str(DLQFields.STATUS): status,
            str(DLQFields.LAST_UPDATED): datetime.now(timezone.utc)
        }

        # Add any additional fields
        for key, value in kwargs.items():
            if key == "next_retry_at":
                update_doc[str(DLQFields.NEXT_RETRY_AT)] = value
            elif key == "retried_at":
                update_doc[str(DLQFields.RETRIED_AT)] = value
            elif key == "discarded_at":
                update_doc[str(DLQFields.DISCARDED_AT)] = value
            elif key == "retry_count":
                update_doc[str(DLQFields.RETRY_COUNT)] = value
            elif key == "discard_reason":
                update_doc[str(DLQFields.DISCARD_REASON)] = value
            elif key == "last_error":
                update_doc[str(DLQFields.LAST_ERROR)] = value
            else:
                update_doc[key] = value

        await self.dlq_collection.update_one(
            {DLQFields.EVENT_ID: event_id},
            {"$set": update_doc}
        )

    async def _retry_message(self, message: DLQMessage) -> None:
        # Trigger before_retry callbacks
        await self._trigger_callbacks("before_retry", message)

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

        # Send to retry topic using confluent-kafka producer
        def delivery_callback(err: Any, msg: Any) -> None:
            if err:
                logger.error(f"Failed to deliver message to retry topic: {err}")

        # Convert headers to the format expected by confluent-kafka
        kafka_headers: list[tuple[str, str | bytes]] = [(k, v) for k, v in headers]

        # Get the original event
        event = message.event

        await asyncio.to_thread(
            self.producer.produce,
            topic=retry_topic,
            value=json.dumps(event.to_dict()).encode(),
            key=message.event_id.encode(),
            headers=kafka_headers,
            callback=delivery_callback
        )

        # Send to original topic
        await asyncio.to_thread(
            self.producer.produce,
            topic=message.original_topic,
            value=json.dumps(event.to_dict()).encode(),
            key=message.event_id.encode(),
            headers=kafka_headers,
            callback=delivery_callback
        )

        # Flush to ensure messages are sent
        await asyncio.to_thread(self.producer.flush, timeout=5)

        # Update metrics
        self.metrics.record_dlq_message_retried(
            message.original_topic,
            message.event_type,
            "success"
        )

        # Update status
        if message.event_id:
            await self._update_message_status(
                message.event_id,
                DLQMessageStatus.RETRIED,
                retried_at=datetime.now(timezone.utc),
                retry_count=message.retry_count + 1
            )

        # Trigger after_retry callbacks
        await self._trigger_callbacks("after_retry", message, success=True)

        logger.info(f"Successfully retried message {message.event_id}")

    async def _discard_message(self, message: DLQMessage, reason: str) -> None:
        # Update metrics
        self.metrics.record_dlq_message_discarded(
            message.original_topic,
            message.event_type,
            reason
        )

        # Update status
        if message.event_id:
            await self._update_message_status(
                message.event_id,
                DLQMessageStatus.DISCARDED,
                discarded_at=datetime.now(timezone.utc),
                discard_reason=reason
            )

        # Trigger callbacks
        await self._trigger_callbacks("on_discard", message, reason)

        logger.warning(f"Discarded message {message.event_id} due to {reason}")

    async def _monitor_dlq(self) -> None:
        while self._running:
            try:
                # Find messages ready for retry
                now = datetime.now(timezone.utc)

                cursor = self.dlq_collection.find({
                    "status": DLQMessageStatus.SCHEDULED,
                    "next_retry_at": {"$lte": now}
                }).limit(100)

                async for doc in cursor:
                    # Recreate DLQ message from MongoDB document
                    message = DLQMessage.from_dict(doc)

                    # Retry message
                    await self._retry_message(message)

                # Update queue size metrics
                await self._update_queue_metrics()

                # Sleep before next check
                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Error in DLQ monitor: {e}")
                await asyncio.sleep(60)

    async def _update_queue_metrics(self) -> None:
        # Get counts by topic
        pipeline: Sequence[Mapping[str, Any]] = [
            {"$match": {str(DLQFields.STATUS): {"$in": [DLQMessageStatus.PENDING,
                                                        DLQMessageStatus.SCHEDULED]}}},
            {"$group": {
                "_id": f"${DLQFields.ORIGINAL_TOPIC}",
                "count": {"$sum": 1}
            }}
        ]

        async for result in self.dlq_collection.aggregate(pipeline):
            # Note: OpenTelemetry doesn't have direct gauge set, using delta tracking
            self.metrics.update_dlq_queue_size(result["_id"], result["count"])

    def set_retry_policy(self, topic: str, policy: RetryPolicy) -> None:
        self._retry_policies[topic] = policy

    def add_filter(self, filter_func: Callable[[DLQMessage], bool]) -> None:
        self._filters.append(filter_func)

    def add_callback(self, event_type: str, callback: Callable[..., Awaitable[None]]) -> None:
        if event_type in self._callbacks:
            self._callbacks[event_type].append(callback)

    async def _trigger_callbacks(self, event_type: str, *args: Any, **kwargs: Any) -> None:
        for callback in self._callbacks.get(event_type, []):
            try:
                await callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in DLQ callback {callback.__name__}: {e}")

    async def retry_message_manually(self, event_id: str) -> bool:
        doc = await self.dlq_collection.find_one({"event_id": event_id})
        if not doc:
            logger.error(f"Message {event_id} not found in DLQ")
            return False

        message = DLQMessage.from_dict(doc)

        await self._retry_message(message)
        return True

    async def get_dlq_stats(self) -> dict[str, Any]:
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

        cursor = self.dlq_collection.aggregate(pipeline)
        results = await cursor.to_list(1)

        # Handle empty collection case
        if not results:
            return {
                "by_status": {},
                "by_topic": [],
                "by_event_type": [],
                "age_stats": {},
                "timestamp": datetime.now(timezone.utc)
            }

        result = results[0]

        return {
            "by_status": {item["_id"]: item["count"] for item in result["by_status"]},
            "by_topic": result["by_topic"],
            "by_event_type": result["by_event_type"],
            "age_stats": result["age_stats"][0] if result["age_stats"] else {},
            "timestamp": datetime.now(timezone.utc)
        }


def create_dlq_manager(
        database: AsyncIOMotorDatabase,
        dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
        retry_topic_suffix: str = "-retry",
        default_retry_policy: RetryPolicy | None = None,
) -> DLQManager:
    if default_retry_policy is None:
        default_retry_policy = RetryPolicy(
            topic="default",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )
    
    return DLQManager(
        database=database,
        dlq_topic=dlq_topic,
        retry_topic_suffix=retry_topic_suffix,
        default_retry_policy=default_retry_policy,
    )
