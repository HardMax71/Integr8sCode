import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence

from confluent_kafka import Consumer, KafkaError, Message, Producer
from opentelemetry.trace import SpanKind

from app.core.database_context import Collection, Database
from app.core.lifecycle import LifecycleEnabled
from app.core.logging import logger
from app.core.metrics.context import get_dlq_metrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer, inject_trace_context
from app.dlq.models import (
    DLQFields,
    DLQMessage,
    DLQMessageStatus,
    DLQMessageUpdate,
    RetryPolicy,
    RetryStrategy,
)
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.events.event_models import CollectionNames
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.mappers.dlq_mapper import DLQMapper
from app.settings import get_settings


class DLQManager(LifecycleEnabled):
    def __init__(
            self,
            database: Database,
            consumer: Consumer,
            producer: Producer,
            dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
            retry_topic_suffix: str = "-retry",
            default_retry_policy: RetryPolicy | None = None,
    ):
        self.metrics = get_dlq_metrics()
        self.dlq_topic = dlq_topic
        self.retry_topic_suffix = retry_topic_suffix
        self.default_retry_policy = default_retry_policy or RetryPolicy(
            topic="default",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )
        self.consumer: Consumer = consumer
        self.producer: Producer = producer
        self.dlq_collection: Collection = database.get_collection(CollectionNames.DLQ_MESSAGES)

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

        topic_name = f"{get_settings().KAFKA_TOPIC_PREFIX}{str(self.dlq_topic)}"
        self.consumer.subscribe([topic_name])

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
        self.consumer.close()
        self.producer.flush(10)

        logger.info("DLQ Manager stopped")

    async def _process_messages(self) -> None:
        while self._running:
            try:
                msg = await self._poll_message()
                if msg is None:
                    continue

                if not await self._validate_message(msg):
                    continue

                start_time = asyncio.get_event_loop().time()
                dlq_message = await self._parse_message(msg)

                await self._record_message_metrics(dlq_message)
                await self._process_message_with_tracing(msg, dlq_message)
                await self._commit_and_record_duration(start_time)

            except Exception as e:
                logger.error(f"Error in DLQ processing loop: {e}")
                await asyncio.sleep(5)

    async def _poll_message(self) -> Message | None:
        """Poll for a message from Kafka."""
        return await asyncio.to_thread(self.consumer.poll, timeout=1.0)

    async def _validate_message(self, msg: Message) -> bool:
        """Validate the Kafka message."""
        if msg.error():
            error = msg.error()
            if error and error.code() == KafkaError._PARTITION_EOF:
                return False
            logger.error(f"Consumer error: {error}")
            return False
        return True

    async def _parse_message(self, msg: Message) -> DLQMessage:
        """Parse Kafka message into DLQMessage."""
        schema_registry = SchemaRegistryManager()
        return DLQMapper.from_kafka_message(msg, schema_registry)

    def _extract_headers(self, msg: Message) -> dict[str, str]:
        """Extract headers from Kafka message."""
        headers_list = msg.headers() or []
        headers: dict[str, str] = {}
        for k, v in headers_list:
            headers[str(k)] = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else (v or "")
        return headers

    async def _record_message_metrics(self, dlq_message: DLQMessage) -> None:
        """Record metrics for received DLQ message."""
        self.metrics.record_dlq_message_received(
            dlq_message.original_topic,
            dlq_message.event_type
        )
        self.metrics.record_dlq_message_age(dlq_message.age_seconds)

    async def _process_message_with_tracing(self, msg: Message, dlq_message: DLQMessage) -> None:
        """Process message with distributed tracing."""
        headers = self._extract_headers(msg)
        ctx = extract_trace_context(headers)
        tracer = get_tracer()

        with tracer.start_as_current_span(
            name="dlq.consume",
            context=ctx,
            kind=SpanKind.CONSUMER,
            attributes={
                str(EventAttributes.KAFKA_TOPIC): str(self.dlq_topic),
                str(EventAttributes.EVENT_TYPE): dlq_message.event_type,
                str(EventAttributes.EVENT_ID): dlq_message.event_id or "",
            },
        ):
            await self._process_dlq_message(dlq_message)

    async def _commit_and_record_duration(self, start_time: float) -> None:
        """Commit offset and record processing duration."""
        await asyncio.to_thread(self.consumer.commit, asynchronous=False)
        duration = asyncio.get_event_loop().time() - start_time
        self.metrics.record_dlq_processing_duration(duration, "process")

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
        await self._update_message_status(
            message.event_id,
            DLQMessageUpdate(status=DLQMessageStatus.SCHEDULED, next_retry_at=next_retry),
        )

        # If immediate retry, process now
        if retry_policy.strategy == RetryStrategy.IMMEDIATE:
            await self._retry_message(message)

    async def _store_message(self, message: DLQMessage) -> None:
        # Ensure message has proper status and timestamps
        message.status = DLQMessageStatus.PENDING
        message.last_updated = datetime.now(timezone.utc)

        doc = DLQMapper.to_mongo_document(message)

        await self.dlq_collection.update_one(
            {DLQFields.EVENT_ID: message.event_id},
            {"$set": doc},
            upsert=True
        )

    async def _update_message_status(self, event_id: str, update: DLQMessageUpdate) -> None:
        update_doc = DLQMapper.update_to_mongo(update)
        await self.dlq_collection.update_one({DLQFields.EVENT_ID: event_id}, {"$set": update_doc})

    async def _retry_message(self, message: DLQMessage) -> None:
        # Trigger before_retry callbacks
        await self._trigger_callbacks("before_retry", message)

        # Send to retry topic first (for monitoring)
        retry_topic = f"{message.original_topic}{self.retry_topic_suffix}"

        hdrs: dict[str, str] = {
            "dlq_retry_count": str(message.retry_count + 1),
            "dlq_original_error": message.error,
            "dlq_retry_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        hdrs = inject_trace_context(hdrs)
        from typing import cast
        kafka_headers = cast(list[tuple[str, str | bytes]], [(k, v.encode()) for k, v in hdrs.items()])

        # Get the original event
        event = message.event

        await asyncio.to_thread(
            self.producer.produce,
            topic=retry_topic,
            value=json.dumps(event.to_dict()).encode(),
            key=message.event_id.encode(),
            headers=kafka_headers,
        )

        # Send to original topic
        await asyncio.to_thread(
            self.producer.produce,
            topic=message.original_topic,
            value=json.dumps(event.to_dict()).encode(),
            key=message.event_id.encode(),
            headers=kafka_headers,
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
        await self._update_message_status(
            message.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.RETRIED,
                retried_at=datetime.now(timezone.utc),
                retry_count=message.retry_count + 1,
            ),
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
        await self._update_message_status(
            message.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.DISCARDED,
                discarded_at=datetime.now(timezone.utc),
                discard_reason=reason,
            ),
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
                    message = DLQMapper.from_mongo_document(doc)

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

        # Guard against invalid states
        status = doc.get(str(DLQFields.STATUS))
        if status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            logger.info(f"Skipping manual retry for {event_id}: status={status}")
            return False

        message = DLQMapper.from_mongo_document(doc)

        await self._retry_message(message)
        return True

def create_dlq_manager(
        database: Database,
        dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
        retry_topic_suffix: str = "-retry",
        default_retry_policy: RetryPolicy | None = None,
) -> DLQManager:

    settings = get_settings()
    consumer = Consumer({
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': f"{GroupId.DLQ_MANAGER}.{settings.KAFKA_GROUP_SUFFIX}",
        'enable.auto.commit': False,
        'auto.offset.reset': 'earliest',
        'client.id': 'dlq-manager-consumer'
    })
    producer = Producer({
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'client.id': 'dlq-manager-producer',
        'acks': 'all',
        'enable.idempotence': True,
        'compression.type': 'gzip',
        'batch.size': 16384,
        'linger.ms': 10
    })
    if default_retry_policy is None:
        default_retry_policy = RetryPolicy(
            topic="default",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )
    return DLQManager(
        database=database,
        consumer=consumer,
        producer=producer,
        dlq_topic=dlq_topic,
        retry_topic_suffix=retry_topic_suffix,
        default_retry_policy=default_retry_policy,
    )
