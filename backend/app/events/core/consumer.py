import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from confluent_kafka import OFFSET_BEGINNING, OFFSET_END, Consumer, Message, TopicPartition
from confluent_kafka.error import KafkaError
from opentelemetry.trace import SpanKind

from app.core.metrics.context import get_event_metrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer
from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.settings import get_settings

from .dispatcher import EventDispatcher
from .types import ConsumerConfig, ConsumerMetrics, ConsumerMetricsSnapshot, ConsumerState, ConsumerStatus


class UnifiedConsumer:
    def __init__(
        self,
        config: ConsumerConfig,
        event_dispatcher: EventDispatcher,
        logger: logging.Logger,
        stats_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self._config = config
        self.logger = logger
        self._schema_registry = SchemaRegistryManager(logger=logger)
        self._dispatcher = event_dispatcher
        self._stats_callback = stats_callback
        self._consumer: Consumer | None = None
        self._state = ConsumerState.STOPPED
        self._running = False
        self._metrics = ConsumerMetrics()
        self._event_metrics = get_event_metrics()  # Singleton for Kafka metrics
        self._error_callback: "Callable[[Exception, BaseEvent], Awaitable[None]] | None" = None
        self._consume_task: asyncio.Task[None] | None = None
        self._topic_prefix = get_settings().KAFKA_TOPIC_PREFIX

    async def start(self, topics: list[KafkaTopic]) -> None:
        self._state = self._state if self._state != ConsumerState.STOPPED else ConsumerState.STARTING

        consumer_config = self._config.to_consumer_config()
        if self._stats_callback:
            consumer_config["stats_cb"] = self._handle_stats

        self._consumer = Consumer(consumer_config)
        topic_strings = [f"{self._topic_prefix}{str(topic)}" for topic in topics]
        self._consumer.subscribe(topic_strings)
        self._running = True
        self._consume_task = asyncio.create_task(self._consume_loop())

        self._state = ConsumerState.RUNNING

        self.logger.info(f"Consumer started for topics: {topic_strings}")

    async def stop(self) -> None:
        self._state = (
            ConsumerState.STOPPING
            if self._state not in (ConsumerState.STOPPED, ConsumerState.STOPPING)
            else self._state
        )

        self._running = False

        if self._consume_task:
            self._consume_task.cancel()
            await asyncio.gather(self._consume_task, return_exceptions=True)
            self._consume_task = None

        await self._cleanup()
        self._state = ConsumerState.STOPPED

    async def _cleanup(self) -> None:
        if self._consumer:
            self._consumer.close()
            self._consumer = None

    async def _consume_loop(self) -> None:
        self.logger.info(f"Consumer loop started for group {self._config.group_id}")
        poll_count = 0
        message_count = 0

        while self._running and self._consumer:
            poll_count += 1
            if poll_count % 100 == 0:  # Log every 100 polls
                self.logger.debug(f"Consumer loop active: polls={poll_count}, messages={message_count}")

            msg = await asyncio.to_thread(self._consumer.poll, timeout=0.1)

            if msg is not None:
                error = msg.error()
                if error:
                    if error.code() != KafkaError._PARTITION_EOF:
                        self.logger.error(f"Consumer error: {error}")
                        self._metrics.processing_errors += 1
                else:
                    message_count += 1
                    self.logger.debug(
                        f"Message received from topic {msg.topic()}, partition {msg.partition()}, offset {msg.offset()}"
                    )
                    await self._process_message(msg)
                    if not self._config.enable_auto_commit:
                        await asyncio.to_thread(self._consumer.commit, msg)
            else:
                await asyncio.sleep(0.01)

        self.logger.warning(
            f"Consumer loop ended for group {self._config.group_id}: "
            f"running={self._running}, consumer={self._consumer is not None}"
        )

    async def _process_message(self, message: Message) -> None:
        topic = message.topic()
        if not topic:
            self.logger.warning("Message with no topic received")
            return

        raw_value = message.value()
        if not raw_value:
            self.logger.warning(f"Empty message from topic {topic}")
            return

        self.logger.debug(f"Deserializing message from topic {topic}, size={len(raw_value)} bytes")
        event = self._schema_registry.deserialize_event(raw_value, topic)
        self.logger.info(f"Deserialized event: type={event.event_type}, id={event.event_id}")

        # Extract trace context from Kafka headers and start a consumer span
        header_list = message.headers() or []
        headers: dict[str, str] = {}
        for k, v in header_list:
            headers[str(k)] = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else (v or "")
        ctx = extract_trace_context(headers)
        tracer = get_tracer()

        # Dispatch event through EventDispatcher
        try:
            self.logger.debug(f"Dispatching {event.event_type} to handlers")
            partition_val = message.partition()
            offset_val = message.offset()
            part_attr = partition_val if partition_val is not None else -1
            off_attr = offset_val if offset_val is not None else -1
            with tracer.start_as_current_span(
                name="kafka.consume",
                context=ctx,
                kind=SpanKind.CONSUMER,
                attributes={
                    EventAttributes.KAFKA_TOPIC: topic,
                    EventAttributes.KAFKA_PARTITION: part_attr,
                    EventAttributes.KAFKA_OFFSET: off_attr,
                    EventAttributes.EVENT_TYPE: event.event_type,
                    EventAttributes.EVENT_ID: event.event_id,
                },
            ):
                await self._dispatcher.dispatch(event)
            self.logger.debug(f"Successfully dispatched {event.event_type}")
            # Update metrics on successful dispatch
            self._metrics.messages_consumed += 1
            self._metrics.bytes_consumed += len(raw_value)
            self._metrics.last_message_time = datetime.now(timezone.utc)
            # Record Kafka consumption metrics
            self._event_metrics.record_kafka_message_consumed(topic=topic, consumer_group=self._config.group_id)
        except Exception as e:
            self.logger.error(f"Dispatcher error for event {event.event_type}: {e}")
            self._metrics.processing_errors += 1
            # Record Kafka consumption error
            self._event_metrics.record_kafka_consumption_error(
                topic=topic, consumer_group=self._config.group_id, error_type=type(e).__name__
            )
            if self._error_callback:
                await self._error_callback(e, event)

    def register_error_callback(self, callback: Callable[[Exception, BaseEvent], Awaitable[None]]) -> None:
        self._error_callback = callback

    def _handle_stats(self, stats_json: str) -> None:
        stats = json.loads(stats_json)

        self._metrics.messages_consumed = stats.get("rxmsgs", 0)
        self._metrics.bytes_consumed = stats.get("rxmsg_bytes", 0)

        topics = stats.get("topics", {})
        self._metrics.consumer_lag = sum(
            partition_stats.get("consumer_lag", 0)
            for topic_stats in topics.values()
            for partition_stats in topic_stats.get("partitions", {}).values()
            if partition_stats.get("consumer_lag", 0) >= 0
        )

        self._metrics.last_updated = datetime.now(timezone.utc)
        self._stats_callback and self._stats_callback(stats)

    @property
    def state(self) -> ConsumerState:
        return self._state

    @property
    def metrics(self) -> ConsumerMetrics:
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._state == ConsumerState.RUNNING

    @property
    def consumer(self) -> Consumer | None:
        return self._consumer

    def get_status(self) -> ConsumerStatus:
        return ConsumerStatus(
            state=self._state.value,
            is_running=self.is_running,
            group_id=self._config.group_id,
            client_id=self._config.client_id,
            metrics=ConsumerMetricsSnapshot(
                messages_consumed=self._metrics.messages_consumed,
                bytes_consumed=self._metrics.bytes_consumed,
                consumer_lag=self._metrics.consumer_lag,
                commit_failures=self._metrics.commit_failures,
                processing_errors=self._metrics.processing_errors,
                last_message_time=(
                    self._metrics.last_message_time.isoformat() if self._metrics.last_message_time else None
                ),
                last_updated=self._metrics.last_updated.isoformat() if self._metrics.last_updated else None,
            ),
        )

    async def seek_to_beginning(self) -> None:
        self._seek_all_partitions(OFFSET_BEGINNING)

    async def seek_to_end(self) -> None:
        self._seek_all_partitions(OFFSET_END)

    def _seek_all_partitions(self, offset_type: int) -> None:
        if not self._consumer:
            self.logger.warning("Cannot seek: consumer not initialized")
            return

        assignment = self._consumer.assignment()
        for partition in assignment:
            new_partition = TopicPartition(partition.topic, partition.partition, offset_type)
            self._consumer.seek(new_partition)

    async def seek_to_offset(self, topic: str, partition: int, offset: int) -> None:
        if not self._consumer:
            self.logger.warning("Cannot seek to offset: consumer not initialized")
            return

        self._consumer.seek(TopicPartition(topic, partition, offset))
