from __future__ import annotations

import asyncio
import logging

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.domain.events.typed import DomainEvent
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


class SSEKafkaRedisBridge(LifecycleEnabled):
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
            logger: logging.Logger,
    ) -> None:
        super().__init__()
        self.schema_registry = schema_registry
        self.settings = settings
        self.event_metrics = event_metrics
        self.sse_bus = sse_bus
        self.logger = logger

        self.num_consumers = settings.SSE_CONSUMER_POOL_SIZE
        self.consumers: list[UnifiedConsumer] = []

    async def _on_start(self) -> None:
        """Start the SSE Kafka→Redis bridge."""
        self.logger.info(f"Starting SSE Kafka→Redis bridge with {self.num_consumers} consumers")

        # Phase 1: Build all consumers and track them immediately (no I/O)
        self.consumers = [self._build_consumer(i) for i in range(self.num_consumers)]

        # Phase 2: Start all in parallel - already tracked in self.consumers for cleanup
        topics = list(CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.WEBSOCKET_GATEWAY])
        await asyncio.gather(*[c.start(topics) for c in self.consumers])

        self.logger.info("SSE Kafka→Redis bridge started successfully")

    async def _on_stop(self) -> None:
        """Stop the SSE Kafka→Redis bridge."""
        self.logger.info("Stopping SSE Kafka→Redis bridge")
        await asyncio.gather(*[c.stop() for c in self.consumers], return_exceptions=True)
        self.consumers.clear()
        self.logger.info("SSE Kafka→Redis bridge stopped")

    def _build_consumer(self, consumer_index: int) -> UnifiedConsumer:
        """Build a consumer instance without starting it."""
        suffix = self.settings.KAFKA_GROUP_SUFFIX
        config = ConsumerConfig(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"sse-bridge-pool.{suffix}",
            client_id=f"sse-bridge-{consumer_index}.{suffix}",
            enable_auto_commit=True,
            auto_offset_reset="latest",
            max_poll_interval_ms=self.settings.KAFKA_MAX_POLL_INTERVAL_MS,
            session_timeout_ms=self.settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self.settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            request_timeout_ms=self.settings.KAFKA_REQUEST_TIMEOUT_MS,
        )

        dispatcher = EventDispatcher(logger=self.logger)
        self._register_routing_handlers(dispatcher)

        return UnifiedConsumer(
            config=config,
            event_dispatcher=dispatcher,
            schema_registry=self.schema_registry,
            settings=self.settings,
            logger=self.logger,
            event_metrics=self.event_metrics,
        )

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

        async def route_event(event: DomainEvent) -> None:
            data = event.model_dump()
            execution_id = data.get("execution_id")
            if not execution_id:
                self.logger.debug(f"Event {event.event_type} has no execution_id")
                return
            try:
                await self.sse_bus.publish_event(execution_id, event)
                self.logger.info(f"Published {event.event_type} to Redis for {execution_id}")
            except Exception as e:
                self.logger.error(
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
            "is_running": self.is_running,
        }


def create_sse_kafka_redis_bridge(
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        event_metrics: EventMetrics,
        sse_bus: SSERedisBus,
        logger: logging.Logger,
) -> SSEKafkaRedisBridge:
    return SSEKafkaRedisBridge(
        schema_registry=schema_registry,
        settings=settings,
        event_metrics=event_metrics,
        sse_bus=sse_bus,
        logger=logger,
    )
