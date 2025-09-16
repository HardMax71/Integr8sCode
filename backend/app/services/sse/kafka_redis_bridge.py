from __future__ import annotations

import asyncio
import os

from app.core.logging import logger
from app.core.metrics.events import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


class SSEKafkaRedisBridge:
    """
    Bridges Kafka events to Redis channels for SSE delivery.

    - Consumes relevant Kafka topics using a small consumer pool
    - Deserializes events and publishes them to Redis via SSERedisBus
    - Keeps no in-process buffers; delivery to clients is via Redis only
    """

    def __init__(
        self,
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        event_metrics: EventMetrics,
        sse_bus: SSERedisBus,
    ) -> None:
        self.schema_registry = schema_registry
        self.settings = settings
        self.event_metrics = event_metrics
        self.sse_bus = sse_bus

        self.num_consumers = settings.SSE_CONSUMER_POOL_SIZE
        self.consumers: list[UnifiedConsumer] = []

        self._lock = asyncio.Lock()
        self._running = False
        self._initialized = False

    async def start(self) -> None:
        async with self._lock:
            if self._initialized:
                return

            logger.info(f"Starting SSE Kafka→Redis bridge with {self.num_consumers} consumers")

            for i in range(self.num_consumers):
                consumer = await self._create_consumer(i)
                self.consumers.append(consumer)

            self._running = True
            self._initialized = True
            logger.info("SSE Kafka→Redis bridge started successfully")

    async def stop(self) -> None:
        async with self._lock:
            if not self._initialized:
                return

            logger.info("Stopping SSE Kafka→Redis bridge")
            self._running = False

            for consumer in self.consumers:
                await consumer.stop()

            self.consumers.clear()
            self._initialized = False
            logger.info("SSE Kafka→Redis bridge stopped")

    async def _create_consumer(self, consumer_index: int) -> UnifiedConsumer:
        suffix = os.environ.get("KAFKA_GROUP_SUFFIX", "")
        group_id = "sse-bridge-pool"
        if suffix:
            group_id = f"{group_id}.{suffix}"
        client_id = f"sse-bridge-{consumer_index}"
        if suffix:
            client_id = f"{client_id}-{suffix}"

        config = ConsumerConfig(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            client_id=client_id,
            enable_auto_commit=True,
            auto_offset_reset="latest",
            max_poll_interval_ms=300000,
            session_timeout_ms=30000,
            heartbeat_interval_ms=3000,
        )

        dispatcher = EventDispatcher()
        self._register_routing_handlers(dispatcher)

        consumer = UnifiedConsumer(config=config, event_dispatcher=dispatcher)

        topics = [
            KafkaTopic.EXECUTION_EVENTS,
            KafkaTopic.EXECUTION_COMPLETED,
            KafkaTopic.EXECUTION_FAILED,
            KafkaTopic.EXECUTION_TIMEOUT,
            KafkaTopic.EXECUTION_RESULTS,
            KafkaTopic.POD_EVENTS,
            KafkaTopic.POD_STATUS_UPDATES,
        ]
        await consumer.start(topics)

        logger.info(f"Bridge consumer {consumer_index} started")
        return consumer

    def _register_routing_handlers(self, dispatcher: EventDispatcher) -> None:
        """Publish relevant events to Redis channels keyed by execution_id."""
        relevant_events = [
            EventType.EXECUTION_REQUESTED,
            EventType.EXECUTION_QUEUED,
            EventType.EXECUTION_STARTED,
            EventType.EXECUTION_RUNNING,
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
            EventType.EXECUTION_CANCELLED,
            EventType.RESULT_STORED,
            EventType.POD_CREATED,
            EventType.POD_SCHEDULED,
            EventType.POD_RUNNING,
            EventType.POD_SUCCEEDED,
            EventType.POD_FAILED,
            EventType.POD_TERMINATED,
            EventType.POD_DELETED,
        ]

        async def route_event(event: BaseEvent) -> None:
            data = event.model_dump()
            execution_id = data.get("execution_id")
            if not execution_id:
                logger.debug(f"Event {event.event_type} has no execution_id")
                return
            try:
                await self.sse_bus.publish_event(execution_id, event)
                logger.info(f"Published {event.event_type} to Redis for {execution_id}")
            except Exception as e:
                logger.error(
                    f"Failed to publish {event.event_type} to Redis for {execution_id}: {e}",
                    exc_info=True,
                )

        for et in relevant_events:
            dispatcher.register_handler(et, route_event)

    def get_stats(self) -> dict[str, int | bool]:
        return {
            "num_consumers": len(self.consumers),
            "active_executions": 0,
            "total_buffers": 0,
            "is_running": self._running,
        }


def create_sse_kafka_redis_bridge(
    schema_registry: SchemaRegistryManager,
    settings: Settings,
    event_metrics: EventMetrics,
    sse_bus: SSERedisBus,
) -> SSEKafkaRedisBridge:
    return SSEKafkaRedisBridge(
        schema_registry=schema_registry,
        settings=settings,
        event_metrics=event_metrics,
        sse_bus=sse_bus,
    )

