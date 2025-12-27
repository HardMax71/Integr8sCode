import asyncio
import json
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Callable, TypeAlias

from confluent_kafka import Message, Producer
from confluent_kafka.error import KafkaError

# Global lock to serialize Producer initialization (workaround for librdkafka race condition)
# See: https://github.com/confluentinc/confluent-kafka-python/issues/1797
_producer_init_lock = threading.Lock()

from app.core.lifecycle import LifecycleEnabled
from app.core.logging import logger
from app.core.metrics.context import get_event_metrics
from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events import BaseEvent
from app.infrastructure.mappers.dlq_mapper import DLQMapper
from app.settings import get_settings

from .types import ProducerConfig, ProducerMetrics, ProducerState

DeliveryCallback: TypeAlias = Callable[[KafkaError | None, Message], None]
StatsCallback: TypeAlias = Callable[[dict[str, Any]], None]


class UnifiedProducer(LifecycleEnabled):
    def __init__(
        self,
        config: ProducerConfig,
        schema_registry_manager: SchemaRegistryManager,
        stats_callback: StatsCallback | None = None,
    ):
        self._config = config
        self._schema_registry = schema_registry_manager
        self._producer: Producer | None = None
        self._stats_callback = stats_callback
        self._state = ProducerState.STOPPED
        self._running = False
        self._metrics = ProducerMetrics()
        self._event_metrics = get_event_metrics()  # Singleton for Kafka metrics
        self._poll_task: asyncio.Task[None] | None = None
        # Topic prefix (for tests/local isolation); cached on init
        self._topic_prefix = get_settings().KAFKA_TOPIC_PREFIX

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
    def producer(self) -> Producer | None:
        return self._producer

    def _handle_delivery(self, error: KafkaError | None, message: Message) -> None:
        if error:
            self._metrics.messages_failed += 1
            self._metrics.last_error = str(error)
            self._metrics.last_error_time = datetime.now(timezone.utc)
            # Record Kafka production error
            topic = message.topic() if message else None
            self._event_metrics.record_kafka_production_error(
                topic=topic if topic is not None else "unknown", error_type=str(error.code())
            )
            logger.error(f"Message delivery failed: {error}")
        else:
            self._metrics.messages_sent += 1
            message_value = message.value()
            if message_value:
                self._metrics.bytes_sent += len(message_value)
            logger.debug(f"Message delivered to {message.topic()}[{message.partition()}]@{message.offset()}")

    def _handle_stats(self, stats_json: str) -> None:
        try:
            stats = json.loads(stats_json)
            self._metrics.queue_size = stats.get("msg_cnt", 0)

            topics = stats.get("topics", {})
            total_messages = 0
            total_latency = 0

            for topic_stats in topics.values():
                partitions = topic_stats.get("partitions", {})
                for partition_stats in partitions.values():
                    msg_cnt = partition_stats.get("msgq_cnt", 0)
                    total_messages += msg_cnt
                    latency = partition_stats.get("rtt", {}).get("avg", 0)
                    if latency > 0 and msg_cnt > 0:
                        total_latency += latency * msg_cnt

            if total_messages > 0:
                self._metrics.avg_latency_ms = total_latency / total_messages

            if self._stats_callback:
                self._stats_callback(stats)
        except Exception as e:
            logger.error(f"Error parsing producer stats: {e}")

    async def start(self) -> None:
        if self._state not in (ProducerState.STOPPED, ProducerState.ERROR):
            logger.warning(f"Producer already in state {self._state}, skipping start")
            return

        self._state = ProducerState.STARTING
        logger.info("Starting producer...")

        producer_config = self._config.to_producer_config()
        producer_config["stats_cb"] = self._handle_stats
        producer_config["statistics.interval.ms"] = 30000

        # Serialize Producer initialization to prevent librdkafka race condition
        with _producer_init_lock:
            self._producer = Producer(producer_config)
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._state = ProducerState.RUNNING

        logger.info(f"Producer started: {self._config.bootstrap_servers}")

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
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

    async def stop(self) -> None:
        if self._state in (ProducerState.STOPPED, ProducerState.STOPPING):
            logger.info(f"Producer already in state {self._state}, skipping stop")
            return

        self._state = ProducerState.STOPPING
        logger.info("Stopping producer...")
        self._running = False

        if self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None

        if self._producer:
            self._producer.flush(timeout=10.0)
            self._producer = None

        self._state = ProducerState.STOPPED
        logger.info("Producer stopped")

    async def _poll_loop(self) -> None:
        logger.info("Started producer poll loop")

        while self._running and self._producer:
            self._producer.poll(timeout=0.1)
            await asyncio.sleep(0.01)

        logger.info("Producer poll loop ended")

    async def produce(
        self, event_to_produce: BaseEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        """
        Produce a message to Kafka.

        Args:
            event_to_produce: Message value (BaseEvent)
            N.B. each instance of BaseEvent has .topic classvar, returning type of KafkaTopic
            key: Message key
            headers: Message headers
        """
        if not self._producer:
            logger.error("Producer not running")
            return

        # Serialize value
        serialized_value = self._schema_registry.serialize_event(event_to_produce)

        topic = f"{self._topic_prefix}{str(event_to_produce.topic)}"
        self._producer.produce(
            topic=topic,
            value=serialized_value,
            key=key.encode() if isinstance(key, str) else key,
            headers=[(k, v.encode()) for k, v in headers.items()] if headers else None,
            callback=self._handle_delivery,
        )

        # Record Kafka metrics
        self._event_metrics.record_kafka_message_produced(topic)

        logger.debug(f"Message [{event_to_produce}] queued for topic: {topic}")

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
            logger.error("Producer not running, cannot send to DLQ")
            return

        try:
            # Get producer ID (hostname + task name)
            current_task = asyncio.current_task()
            task_name = current_task.get_name() if current_task else "main"
            producer_id = f"{socket.gethostname()}-{task_name}"

            # Create DLQ message
            dlq_message = DLQMapper.from_failed_event(
                event=original_event,
                original_topic=original_topic,
                error=str(error),
                producer_id=producer_id,
                retry_count=retry_count,
            )

            # Create DLQ event wrapper
            dlq_event_data = {
                "event_id": dlq_message.event_id or original_event.event_id,
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

            # Send to DLQ topic
            self._producer.produce(
                topic=f"{self._topic_prefix}{str(KafkaTopic.DEAD_LETTER_QUEUE)}",
                value=serialized_value,
                key=original_event.event_id.encode() if original_event.event_id else None,
                headers=[
                    ("original_topic", original_topic.encode()),
                    ("error_type", type(error).__name__.encode()),
                    ("retry_count", str(retry_count).encode()),
                ],
                callback=self._handle_delivery,
            )

            # Record metrics
            self._event_metrics.record_kafka_message_produced(
                f"{self._topic_prefix}{str(KafkaTopic.DEAD_LETTER_QUEUE)}"
            )
            self._metrics.messages_sent += 1

            logger.warning(
                f"Event {original_event.event_id} sent to DLQ. "
                f"Original topic: {original_topic}, Error: {error}, "
                f"Retry count: {retry_count}"
            )

        except Exception as e:
            # If we can't send to DLQ, log critically but don't crash
            logger.critical(
                f"Failed to send event {original_event.event_id} to DLQ: {e}. Original error: {error}", exc_info=True
            )
            self._metrics.messages_failed += 1
