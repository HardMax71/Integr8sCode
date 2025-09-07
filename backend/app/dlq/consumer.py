import asyncio
from datetime import timedelta
from typing import Any, Callable, Dict, List

from confluent_kafka import OFFSET_BEGINNING, OFFSET_END, Message, TopicPartition

from app.core.logging import logger
from app.dlq.models import DLQMessage
from app.domain.enums.events import EventType
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.producer import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.settings import get_settings


class DLQConsumer:
    def __init__(
            self,
            dlq_topic: KafkaTopic,
            producer: UnifiedProducer,
            schema_registry_manager: SchemaRegistryManager,
            group_id: GroupId = GroupId.DLQ_PROCESSOR,
            max_retry_attempts: int = 5,
            retry_delay_hours: int = 1,
            max_age_days: int = 7,
            batch_size: int = 100,
    ):
        self.dlq_topic = dlq_topic
        self.group_id = group_id
        self.max_retry_attempts = max_retry_attempts
        self.retry_delay = timedelta(hours=retry_delay_hours)
        self.max_age = timedelta(days=max_age_days)
        self.batch_size = batch_size

        # Create consumer config
        settings = get_settings()
        self.config = ConsumerConfig(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            max_poll_records=batch_size,
            enable_auto_commit=False,
        )

        self.consumer: UnifiedConsumer | None = None
        self.producer: UnifiedProducer = producer
        self.schema_registry_manager = schema_registry_manager
        self.dispatcher = EventDispatcher()
        self._retry_handlers: Dict[str, Callable] = {}
        self._permanent_failure_handlers: List[Callable] = []
        self._running = False
        self._process_task: asyncio.Task | None = None

        # Statistics
        self.stats = {
            "processed": 0,
            "retried": 0,
            "permanently_failed": 0,
            "expired": 0,
            "errors": 0
        }

    async def start(self) -> None:
        """Start the DLQ consumer"""
        if self._running:
            return

        self.consumer = UnifiedConsumer(
            self.config,
            event_dispatcher=self.dispatcher
        )

        # Register handler for DLQ events through dispatcher
        # DLQ messages are generic, so we handle all event types
        for event_type in EventType:
            self.dispatcher.register(event_type)(self._process_dlq_event)

        await self.consumer.start([self.dlq_topic])
        self._running = True

        # Start periodic processing
        self._process_task = asyncio.create_task(self._periodic_process())

        logger.info(f"DLQ consumer started for topic: {self.dlq_topic}")

    async def _process_dlq_event(self, event: BaseEvent) -> None:
        """Process a single DLQ event from dispatcher."""
        try:
            # Extract DLQ-specific attributes from the event
            # These should be added by the producer when sending to DLQ
            original_topic = getattr(event, 'original_topic', str(event.topic))
            error = getattr(event, 'error', 'Unknown error')
            retry_count = getattr(event, 'retry_count', 0)
            producer_id = getattr(event, 'producer_id', 'unknown')

            # Create DLQMessage from the failed event
            dlq_message = DLQMessage.from_failed_event(
                event=event,
                original_topic=original_topic,
                error=error,
                producer_id=producer_id,
                retry_count=retry_count
            )

            # Process the message based on retry policy
            self.stats["processed"] += 1

            # Check if message is too old
            if dlq_message.age > self.max_age:
                await self._handle_expired_messages([dlq_message])
                return

            # Check retry count
            if dlq_message.retry_count >= self.max_retry_attempts:
                await self._handle_permanent_failures([dlq_message])
                return

            # Check if enough time has passed for retry
            if dlq_message.age >= self.retry_delay:
                await self._retry_messages([dlq_message])
            else:
                # Message is not ready for retry yet
                logger.debug(f"Message {dlq_message.event_id} not ready for retry yet")

        except Exception as e:
            logger.error(f"Failed to process DLQ event: {e}", exc_info=True)
            self.stats["errors"] += 1

    async def _process_dlq_message(self, message: Message) -> None:
        """Process a single DLQ message from confluent-kafka Message"""
        try:
            dlq_message = DLQMessage.from_kafka_message(message, self.schema_registry_manager)

            # Process individual message similar to batch processing
            self.stats["processed"] += 1

            # Check if message is too old
            if dlq_message.age > self.max_age:
                await self._handle_expired_messages([dlq_message])
                return

            # Check retry count
            if dlq_message.retry_count >= self.max_retry_attempts:
                await self._handle_permanent_failures([dlq_message])
                return

            # Check if enough time has passed for retry
            if dlq_message.age >= self.retry_delay:
                await self._retry_messages([dlq_message])
            else:
                # Message is not ready for retry yet, skip
                logger.debug(f"Message {dlq_message.event_id} not ready for retry yet")

        except Exception as e:
            logger.error(f"Failed to process DLQ message: {e}")
            self.stats["errors"] += 1

    async def stop(self) -> None:
        """Stop the DLQ consumer"""
        if not self._running:
            return

        self._running = False

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        if self.consumer:
            await self.consumer.stop()

        logger.info(f"DLQ consumer stopped. Stats: {self.stats}")

    def add_retry_handler(self, event_type: str, handler: Callable) -> None:
        self._retry_handlers[event_type] = handler

    def add_permanent_failure_handler(self, handler: Callable) -> None:
        self._permanent_failure_handlers.append(handler)

    async def _periodic_process(self) -> None:
        while self._running:
            try:
                # Process is triggered by the consumer's batch handler
                await asyncio.sleep(60)  # Check every minute

                # Log statistics
                logger.info(f"DLQ stats: {self.stats}")

            except Exception as e:
                logger.error(f"Error in DLQ periodic process: {e}")
                await asyncio.sleep(60)

    async def _process_dlq_batch(self, events: List[tuple]) -> None:
        dlq_messages = []

        # Convert to DLQMessage objects
        for _, record in events:
            try:
                dlq_message = DLQMessage.from_kafka_message(record, self.schema_registry_manager)
                dlq_messages.append(dlq_message)
            except Exception as e:
                logger.error(f"Failed to parse DLQ message: {e}")
                self.stats["errors"] += 1

        # Group messages by action
        to_retry = []
        permanently_failed = []
        expired = []

        for msg in dlq_messages:
            self.stats["processed"] += 1

            # Check if message is too old
            if msg.age > self.max_age:
                expired.append(msg)
                continue

            # Check retry count
            if msg.retry_count >= self.max_retry_attempts:
                permanently_failed.append(msg)
                continue

            # Check if enough time has passed for retry
            if msg.age >= self.retry_delay:
                to_retry.append(msg)
            else:
                # Message is not ready for retry yet, skip
                continue

        # Process each group
        await self._retry_messages(to_retry)
        await self._handle_permanent_failures(permanently_failed)
        await self._handle_expired_messages(expired)

    async def _retry_messages(self, messages: List[DLQMessage]) -> None:
        if not messages:
            return

        for msg in messages:
            try:
                # Check if there's a custom retry handler
                handler = self._retry_handlers.get(msg.event_type)

                if handler:
                    # Use custom handler
                    if asyncio.iscoroutinefunction(handler):
                        should_retry = await handler(msg)
                    else:
                        should_retry = await asyncio.to_thread(handler, msg)

                    if not should_retry:
                        logger.info(
                            f"Custom handler rejected retry for event {msg.event_id}"
                        )
                        continue

                # Get the original event
                event = msg.event
                if not event:
                    logger.error(f"Failed to get event {msg.event_id} for retry")
                    self.stats["errors"] += 1
                    continue

                # Add retry metadata to headers
                headers = {
                    "retry_count": str(msg.retry_count + 1),
                    "retry_from_dlq": "true",
                    "original_error": msg.error[:100],  # Truncate long errors
                    "dlq_timestamp": msg.failed_at.isoformat()
                }

                # Send back to original topic
                await self.producer.produce(
                    event_to_produce=event,
                    headers=headers
                )
                success = True

                if success:
                    logger.info(
                        f"Retried event {msg.event_id} to topic {msg.original_topic} "
                        f"(attempt {msg.retry_count + 1})"
                    )
                    self.stats["retried"] += 1
                else:
                    logger.error(f"Failed to retry event {msg.event_id}")
                    self.stats["errors"] += 1

            except Exception as e:
                logger.error(f"Error retrying message {msg.event_id}: {e}")
                self.stats["errors"] += 1

    async def _handle_permanent_failures(self, messages: List[DLQMessage]) -> None:
        if not messages:
            return

        for msg in messages:
            try:
                logger.warning(
                    f"Event {msg.event_id} permanently failed after "
                    f"{msg.retry_count} attempts. Error: {msg.error}"
                )

                # Call permanent failure handlers
                for handler in self._permanent_failure_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(msg)
                        else:
                            await asyncio.to_thread(handler, msg)
                    except Exception as e:
                        logger.error(f"Permanent failure handler error: {e}")

                self.stats["permanently_failed"] += 1

            except Exception as e:
                logger.error(f"Error handling permanent failure: {e}")
                self.stats["errors"] += 1

    async def _handle_expired_messages(self, messages: List[DLQMessage]) -> None:
        if not messages:
            return

        for msg in messages:
            logger.warning(
                f"Event {msg.event_id} expired (age: {msg.age.days} days). "
                f"Will not retry."
            )
            self.stats["expired"] += 1

    async def reprocess_all(
            self,
            event_types: List[str] | None = None,
            force: bool = False
    ) -> Dict[str, int]:
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        logger.info(
            f"Reprocessing all DLQ messages"
            f"{f' for types: {event_types}' if event_types else ''}"
        )

        # Seek to beginning using native confluent-kafka
        if self.consumer.consumer:
            try:
                # Get current assignment
                assignment = self.consumer.consumer.assignment()
                if assignment:
                    for partition in assignment:
                        # Create new TopicPartition with desired offset
                        new_partition = TopicPartition(partition.topic, partition.partition, OFFSET_BEGINNING)
                        self.consumer.consumer.seek(new_partition)
                    logger.info(f"Seeked {len(assignment)} partitions to beginning")
            except Exception as e:
                logger.error(f"Failed to seek to beginning: {e}")

        # Temporarily adjust settings for bulk reprocessing
        original_retry_delay = self.retry_delay
        if force:
            self.retry_delay = timedelta(seconds=0)

        # Process until caught up
        reprocess_stats = {
            "total": 0,
            "retried": 0,
            "skipped": 0,
            "errors": 0
        }

        try:
            # Process messages
            # This will be handled by the batch processor

            # Wait for processing to complete
            await asyncio.sleep(5)

            # Copy stats
            reprocess_stats["total"] = self.stats["processed"]
            reprocess_stats["retried"] = self.stats["retried"]
            reprocess_stats["errors"] = self.stats["errors"]

        finally:
            # Restore original settings
            self.retry_delay = original_retry_delay

            # Seek back to end for normal processing using native confluent-kafka
            if self.consumer.consumer:
                try:
                    # Get current assignment
                    assignment = self.consumer.consumer.assignment()
                    if assignment:
                        for partition in assignment:
                            # Create new TopicPartition with desired offset
                            new_partition = TopicPartition(partition.topic, partition.partition, OFFSET_END)
                            self.consumer.consumer.seek(new_partition)
                        logger.info(f"Seeked {len(assignment)} partitions to end")
                except Exception as e:
                    logger.error(f"Failed to seek to end: {e}")

        return reprocess_stats

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "topic": self.dlq_topic,
            "group_id": self.group_id,
            "running": self._running,
            "config": {
                "max_retry_attempts": self.max_retry_attempts,
                "retry_delay_hours": self.retry_delay.total_seconds() / 3600,
                "max_age_days": self.max_age.days,
                "batch_size": self.batch_size
            }
        }


class DLQConsumerRegistry:
    def __init__(self) -> None:
        self._consumers: Dict[str, DLQConsumer] = {}

    def get(self, topic: str) -> DLQConsumer | None:
        return self._consumers.get(topic)

    def register(self, consumer: DLQConsumer) -> None:
        self._consumers[consumer.dlq_topic] = consumer

    async def start_all(self) -> None:
        for consumer in self._consumers.values():
            await consumer.start()

    async def stop_all(self) -> None:
        tasks = []
        for consumer in self._consumers.values():
            tasks.append(consumer.stop())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def create_dlq_consumer_registry() -> DLQConsumerRegistry:
    return DLQConsumerRegistry()
