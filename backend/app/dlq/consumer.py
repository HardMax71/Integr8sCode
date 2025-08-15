import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from aiokafka.structs import ConsumerRecord

from app.core.logging import logger
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.consumer_group_names import GroupId
from app.events.core.producer import UnifiedProducer, create_unified_producer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.schemas_avro.event_schemas import BaseEvent, deserialize_event


class DLQMessage:
    """Represents a message in the Dead Letter Queue"""

    def __init__(self, record: ConsumerRecord):
        self.record = record
        self.data = json.loads(record.value.decode('utf-8'))
        self.event_data = self.data.get("event", {})
        self.original_topic = self.data.get("original_topic")
        self.error = self.data.get("error")
        self.retry_count = self.data.get("retry_count", 0)
        self.failed_at = datetime.fromisoformat(self.data.get("failed_at"))
        self.producer_id = self.data.get("producer_id")

        # Parse headers
        self.headers = {}
        if record.headers:
            for key, value in record.headers:
                self.headers[key] = value.decode('utf-8') if value else None

    @property
    def event_id(self) -> str:
        """Get event ID"""
        return str(self.event_data.get("event_id", "unknown"))

    @property
    def event_type(self) -> str:
        """Get event type"""
        return str(self.event_data.get("event_type", "unknown"))

    @property
    def age(self) -> timedelta:
        """Get age of the failed message"""
        return datetime.now(timezone.utc) - self.failed_at

    def deserialize_event(self) -> Optional[BaseEvent]:
        """Deserialize the original event"""
        try:
            return deserialize_event(self.event_data)
        except Exception as e:
            logger.error(f"Failed to deserialize DLQ event: {e}")
            return None


class DLQConsumer:
    """Consumer specifically for Dead Letter Queue processing"""

    def __init__(
            self,
            dlq_topic: str,
            group_id: str = GroupId.DLQ_PROCESSOR,
            max_retry_attempts: int = 5,
            retry_delay_hours: int = 1,
            max_age_days: int = 7,
            batch_size: int = 100,
            producer: Optional[UnifiedProducer] = None,
            schema_registry_manager: Optional[SchemaRegistryManager] = None,
    ):
        self.dlq_topic = dlq_topic
        self.group_id = group_id
        self.max_retry_attempts = max_retry_attempts
        self.retry_delay = timedelta(hours=retry_delay_hours)
        self.max_age = timedelta(days=max_age_days)
        self.batch_size = batch_size

        # Create consumer config
        self.config = ConsumerConfig(
            group_id=group_id,
            topics=[dlq_topic],
            max_poll_records=batch_size,
            enable_auto_commit=False,
        )

        self.consumer: Optional[UnifiedConsumer] = None
        self.producer: Optional[UnifiedProducer] = producer
        self._producer_provided = producer is not None
        self.schema_registry_manager = schema_registry_manager
        self._retry_handlers: Dict[str, Callable] = {}
        self._permanent_failure_handlers: List[Callable] = []
        self._running = False
        self._process_task: Optional[asyncio.Task] = None

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

        # Create producer if not provided
        if not self.producer:
            self.producer = create_unified_producer()
            await self.producer.start()

        self.consumer = UnifiedConsumer(self.config, self.schema_registry_manager)

        # Set up batch handler with proper signature
        async def batch_handler(event: BaseEvent | dict[str, Any], record: Any) -> Any:
            # Extract batch from record
            if hasattr(record, 'batch'):
                await self._process_dlq_batch(record.batch)
            return None
        
        self.consumer.register_handler("__batch__", batch_handler)

        await self.consumer.start()
        self._running = True

        # Start periodic processing
        self._process_task = asyncio.create_task(self._periodic_process())

        logger.info(f"DLQ consumer started for topic: {self.dlq_topic}")

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

        # Stop producer if we created it
        if self.producer and not self._producer_provided:
            await self.producer.stop()

        logger.info(f"DLQ consumer stopped. Stats: {self.stats}")

    def add_retry_handler(self, event_type: str, handler: Callable) -> None:
        """Add handler for retrying specific event types"""
        self._retry_handlers[event_type] = handler

    def add_permanent_failure_handler(self, handler: Callable) -> None:
        """Add handler for permanently failed messages"""
        self._permanent_failure_handlers.append(handler)

    async def _periodic_process(self) -> None:
        """Periodically trigger processing"""
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
        """Process a batch of DLQ messages"""
        dlq_messages = []

        # Convert to DLQMessage objects
        for _, record in events:
            try:
                dlq_message = DLQMessage(record)
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
        """Retry messages by sending them back to original topic"""
        if not messages:
            return

        if not self.producer:
            logger.error("Producer not available for retrying messages")
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

                # Deserialize original event
                event = msg.deserialize_event()
                if not event:
                    logger.error(f"Failed to deserialize event {msg.event_id} for retry")
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
                success = await self.producer.send_event(
                    event,
                    msg.original_topic,
                    headers=headers
                )

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
        """Handle messages that have exceeded retry attempts"""
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
        """Handle messages that are too old"""
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
            event_types: Optional[List[str]] = None,
            force: bool = False
    ) -> Dict[str, int]:
        """Reprocess all messages in DLQ"""
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        logger.info(
            f"Reprocessing all DLQ messages"
            f"{f' for types: {event_types}' if event_types else ''}"
        )

        # Seek to beginning
        await self.consumer.seek_to_beginning()

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

            # Seek back to end for normal processing
            await self.consumer.seek_to_end()

        return reprocess_stats

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
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
    """Registry for managing multiple DLQ consumers"""

    def __init__(self) -> None:
        self._consumers: Dict[str, DLQConsumer] = {}

    def get(self, topic: str) -> Optional[DLQConsumer]:
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
    """Factory function to create a DLQ consumer registry.
    
    Returns:
        A new DLQ consumer registry instance
    """
    return DLQConsumerRegistry()
