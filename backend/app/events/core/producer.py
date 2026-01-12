import asyncio
import json
import logging
import socket
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics.context import get_event_metrics
from app.dlq.models import DLQMessage, DLQMessageStatus
from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events import BaseEvent
from app.settings import Settings

from .types import ProducerConfig, ProducerMetrics, ProducerState


class UnifiedProducer(LifecycleEnabled):
    """Fully async Kafka producer using aiokafka."""

    def __init__(
        self,
        config: ProducerConfig,
        schema_registry_manager: SchemaRegistryManager,
        logger: logging.Logger,
        settings: Settings,
    ):
        super().__init__()
        self._config = config
        self._schema_registry = schema_registry_manager
        self.logger = logger
        self._producer: AIOKafkaProducer | None = None
        self._state = ProducerState.STOPPED
        self._metrics = ProducerMetrics()
        self._event_metrics = get_event_metrics()
        self._topic_prefix = settings.KAFKA_TOPIC_PREFIX

    @property
    def is_running(self) -> bool:
        return self._state == ProducerState.RUNNING

    @property
    def state(self) -> ProducerState:
        return self._state

    @property
    def metrics(self) -> ProducerMetrics:
        return self._metrics

    @property
    def producer(self) -> AIOKafkaProducer | None:
        return self._producer

    async def _on_start(self) -> None:
        """Start the Kafka producer."""
        self._state = ProducerState.STARTING
        self.logger.info("Starting producer...")

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._config.bootstrap_servers,
            client_id=self._config.client_id,
            acks=self._config.acks,
            compression_type=self._config.compression_type,
            max_batch_size=self._config.batch_size,
            linger_ms=self._config.linger_ms,
            enable_idempotence=self._config.enable_idempotence,
        )

        await self._producer.start()
        self._state = ProducerState.RUNNING
        self.logger.info(f"Producer started: {self._config.bootstrap_servers}")

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "running": self.is_running,
            "config": {
                "bootstrap_servers": self._config.bootstrap_servers,
                "client_id": self._config.client_id,
                "batch_size": self._config.batch_size,
                "compression_type": self._config.compression_type,
            },
            "metrics": {
                "messages_sent": self._metrics.messages_sent,
                "messages_failed": self._metrics.messages_failed,
                "bytes_sent": self._metrics.bytes_sent,
                "queue_size": self._metrics.queue_size,
                "avg_latency_ms": self._metrics.avg_latency_ms,
                "last_error": self._metrics.last_error,
                "last_error_time": self._metrics.last_error_time.isoformat() if self._metrics.last_error_time else None,
            },
        }

    async def _on_stop(self) -> None:
        """Stop the Kafka producer."""
        self._state = ProducerState.STOPPING
        self.logger.info("Stopping producer...")

        if self._producer:
            await self._producer.stop()
            self._producer = None

        self._state = ProducerState.STOPPED
        self.logger.info("Producer stopped")

    async def produce(
        self, event_to_produce: BaseEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        """
        Produce a message to Kafka.

        Args:
            event_to_produce: Message value (BaseEvent)
            key: Message key
            headers: Message headers
        """
        if not self._producer:
            self.logger.error("Producer not running")
            return

        try:
            # Serialize value using async schema registry
            serialized_value = await self._schema_registry.serialize_event(event_to_produce)

            topic = f"{self._topic_prefix}{str(event_to_produce.topic)}"

            # Convert headers to list of tuples format
            header_list = [(k, v.encode()) for k, v in headers.items()] if headers else None

            await self._producer.send_and_wait(
                topic=topic,
                value=serialized_value,
                key=key.encode() if isinstance(key, str) else key,
                headers=header_list,
            )

            # Update metrics on success
            self._metrics.messages_sent += 1
            self._metrics.bytes_sent += len(serialized_value)

            # Record Kafka metrics
            self._event_metrics.record_kafka_message_produced(topic)

            self.logger.debug(f"Message [{event_to_produce}] sent to topic: {topic}")

        except KafkaError as e:
            self._metrics.messages_failed += 1
            self._metrics.last_error = str(e)
            self._metrics.last_error_time = datetime.now(timezone.utc)
            self._event_metrics.record_kafka_production_error(
                topic=f"{self._topic_prefix}{str(event_to_produce.topic)}", error_type=type(e).__name__
            )
            self.logger.error(f"Failed to produce message: {e}")
            raise

    async def send_to_dlq(
        self, original_event: BaseEvent, original_topic: str, error: Exception, retry_count: int = 0
    ) -> None:
        """
        Send a failed event to the Dead Letter Queue.

        Args:
            original_event: The event that failed processing
            original_topic: The topic where the event originally failed
            error: The exception that caused the failure
            retry_count: Number of retry attempts already made
        """
        if not self._producer:
            self.logger.error("Producer not running, cannot send to DLQ")
            return

        try:
            # Get producer ID (hostname + task name)
            current_task = asyncio.current_task()
            task_name = current_task.get_name() if current_task else "main"
            producer_id = f"{socket.gethostname()}-{task_name}"

            # Create DLQ message directly
            dlq_message = DLQMessage(
                event_id=original_event.event_id,
                event=original_event,
                event_type=original_event.event_type,
                original_topic=original_topic,
                error=str(error),
                retry_count=retry_count,
                failed_at=datetime.now(timezone.utc),
                status=DLQMessageStatus.PENDING,
                producer_id=producer_id,
            )

            # Create DLQ event wrapper
            dlq_event_data = {
                "event_id": dlq_message.event_id,
                "event_type": "dlq.message",
                "event": dlq_message.event.to_dict(),
                "original_topic": dlq_message.original_topic,
                "error": dlq_message.error,
                "retry_count": dlq_message.retry_count,
                "failed_at": dlq_message.failed_at.isoformat(),
                "producer_id": dlq_message.producer_id,
                "status": str(dlq_message.status),
            }

            # Serialize as JSON (DLQ uses JSON format for flexibility)
            serialized_value = json.dumps(dlq_event_data).encode("utf-8")

            dlq_topic = f"{self._topic_prefix}{str(KafkaTopic.DEAD_LETTER_QUEUE)}"

            # Send to DLQ topic
            await self._producer.send_and_wait(
                topic=dlq_topic,
                value=serialized_value,
                key=original_event.event_id.encode() if original_event.event_id else None,
                headers=[
                    ("original_topic", original_topic.encode()),
                    ("error_type", type(error).__name__.encode()),
                    ("retry_count", str(retry_count).encode()),
                ],
            )

            # Record metrics
            self._event_metrics.record_kafka_message_produced(dlq_topic)
            self._metrics.messages_sent += 1

            self.logger.warning(
                f"Event {original_event.event_id} sent to DLQ. "
                f"Original topic: {original_topic}, Error: {error}, "
                f"Retry count: {retry_count}"
            )

        except Exception as e:
            # If we can't send to DLQ, log critically but don't crash
            self.logger.critical(
                f"Failed to send event {original_event.event_id} to DLQ: {e}. Original error: {error}", exc_info=True
            )
            self._metrics.messages_failed += 1
