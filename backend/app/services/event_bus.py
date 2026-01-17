import asyncio
import fnmatch
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError
from fastapi import Request
from pydantic import BaseModel, ConfigDict

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics import ConnectionMetrics
from app.domain.enums.kafka import KafkaTopic
from app.settings import Settings


class EventBusEvent(BaseModel):
    """Represents an event on the event bus."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]


@dataclass
class Subscription:
    """Represents a single event subscription."""

    id: str = field(default_factory=lambda: str(uuid4()))
    pattern: str = ""
    handler: Callable[[EventBusEvent], Any] = field(default=lambda _: None)


class EventBus(LifecycleEnabled):
    """
    Distributed event bus for cross-instance communication via Kafka.

    Publishers send events to Kafka. Subscribers receive events from OTHER instances
    only - self-published messages are filtered out. This design means:
    - Publishers should update their own state directly before calling publish()
    - Handlers only run for events from other instances (cache invalidation, etc.)

    Supports pattern-based subscriptions using wildcards:
    - execution.* - matches all execution events
    - execution.123.* - matches all events for execution 123
    - *.completed - matches all completed events
    """

    def __init__(self, settings: Settings, logger: logging.Logger, connection_metrics: ConnectionMetrics) -> None:
        super().__init__()
        self.logger = logger
        self.settings = settings
        self.metrics = connection_metrics
        self.producer: Optional[AIOKafkaProducer] = None
        self.consumer: Optional[AIOKafkaConsumer] = None
        self._subscriptions: dict[str, Subscription] = {}  # id -> Subscription
        self._pattern_index: dict[str, set[str]] = {}  # pattern -> set of subscription ids
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._topic = f"{self.settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.EVENT_BUS_STREAM}"
        self._instance_id = str(uuid4())  # Unique ID for filtering self-published messages

    async def _on_start(self) -> None:
        """Start the event bus with Kafka backing."""
        await self._initialize_kafka()
        self._consumer_task = asyncio.create_task(self._kafka_listener())
        self.logger.info("Event bus started with Kafka backing")

    async def _initialize_kafka(self) -> None:
        """Initialize Kafka producer and consumer."""
        # Producer setup
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id=f"event-bus-producer-{uuid4()}",
            linger_ms=10,
            max_batch_size=16384,
            enable_idempotence=True,
        )
        await self.producer.start()

        # Consumer setup
        self.consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"event-bus-{uuid4()}",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            client_id=f"event-bus-consumer-{uuid4()}",
            session_timeout_ms=self.settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self.settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            max_poll_interval_ms=self.settings.KAFKA_MAX_POLL_INTERVAL_MS,
            request_timeout_ms=self.settings.KAFKA_REQUEST_TIMEOUT_MS,
        )
        await self.consumer.start()

    async def _on_stop(self) -> None:
        """Stop the event bus and clean up resources."""
        # Cancel consumer task
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        # Stop Kafka components
        if self.consumer:
            await self.consumer.stop()
            self.consumer = None

        if self.producer:
            await self.producer.stop()
            self.producer = None

        # Clear subscriptions
        async with self._lock:
            self._subscriptions.clear()
            self._pattern_index.clear()

        self.logger.info("Event bus stopped")

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Publish an event to Kafka for cross-instance distribution.

        Local handlers receive events only from OTHER instances via the Kafka listener.
        Publishers should update their own state directly before calling publish().

        Args:
            event_type: Event type (e.g., "execution.123.started")
            data: Event data payload
        """
        event = self._create_event(event_type, data)

        if self.producer:
            try:
                value = event.model_dump_json().encode("utf-8")
                key = event_type.encode("utf-8") if event_type else None
                headers = [("source_instance", self._instance_id.encode("utf-8"))]

                await self.producer.send_and_wait(
                    topic=self._topic,
                    value=value,
                    key=key,
                    headers=headers,
                )
            except Exception as e:
                self.logger.error(f"Failed to publish to Kafka: {e}")

    def _create_event(self, event_type: str, data: dict[str, Any]) -> EventBusEvent:
        """Create a standardized event object."""
        return EventBusEvent(
            id=str(uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=data,
        )

    async def subscribe(self, pattern: str, handler: Callable[[EventBusEvent], Any]) -> str:
        """
        Subscribe to events matching a pattern.

        Args:
            pattern: Event pattern with wildcards (e.g., "execution.*")
            handler: Async function to handle matching events

        Returns:
            Subscription ID for later unsubscribe
        """
        subscription = Subscription(pattern=pattern, handler=handler)

        async with self._lock:
            # Store subscription
            self._subscriptions[subscription.id] = subscription

            # Update pattern index
            if pattern not in self._pattern_index:
                self._pattern_index[pattern] = set()
            self._pattern_index[pattern].add(subscription.id)

            # Update metrics
            self._update_metrics(pattern)

        self.logger.debug(f"Created subscription {subscription.id} for pattern: {pattern}")
        return subscription.id

    async def unsubscribe(self, pattern: str, handler: Callable[[EventBusEvent], Any]) -> None:
        """Unsubscribe a specific handler from a pattern."""
        async with self._lock:
            # Find subscription with matching pattern and handler
            for sub_id, subscription in list(self._subscriptions.items()):
                if subscription.pattern == pattern and subscription.handler == handler:
                    await self._remove_subscription(sub_id)
                    return

            self.logger.warning(f"No subscription found for pattern {pattern} with given handler")

    async def _remove_subscription(self, subscription_id: str) -> None:
        """Remove a subscription by ID (must be called within lock)."""
        if subscription_id not in self._subscriptions:
            self.logger.warning(f"Subscription {subscription_id} not found")
            return

        subscription = self._subscriptions[subscription_id]
        pattern = subscription.pattern

        # Remove from subscriptions
        del self._subscriptions[subscription_id]

        # Update pattern index
        if pattern in self._pattern_index:
            self._pattern_index[pattern].discard(subscription_id)
            if not self._pattern_index[pattern]:
                del self._pattern_index[pattern]

        # Update metrics
        self._update_metrics(pattern)

        self.logger.debug(f"Removed subscription {subscription_id} for pattern: {pattern}")

    async def _distribute_event(self, event_type: str, event: EventBusEvent) -> None:
        """Distribute event to all matching local subscribers."""
        # Find matching subscriptions
        matching_handlers = await self._find_matching_handlers(event_type)

        if not matching_handlers:
            return

        # Execute all handlers concurrently
        results = await asyncio.gather(
            *(self._invoke_handler(handler, event) for handler in matching_handlers), return_exceptions=True
        )

        # Log any errors
        for _i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Handler failed for event {event_type}: {result}")

    async def _find_matching_handlers(self, event_type: str) -> list[Callable[[EventBusEvent], Any]]:
        """Find all handlers matching the event type."""
        async with self._lock:
            handlers: list[Callable[[EventBusEvent], Any]] = []
            for pattern, sub_ids in self._pattern_index.items():
                if fnmatch.fnmatch(event_type, pattern):
                    handlers.extend(
                        self._subscriptions[sub_id].handler for sub_id in sub_ids if sub_id in self._subscriptions
                    )
            return handlers

    async def _invoke_handler(self, handler: Callable[[EventBusEvent], Any], event: EventBusEvent) -> None:
        """Invoke a single handler, handling both sync and async."""
        if asyncio.iscoroutinefunction(handler):
            await handler(event)
        else:
            await asyncio.to_thread(handler, event)

    async def _kafka_listener(self) -> None:
        """Listen for Kafka messages from OTHER instances and distribute to local subscribers."""
        if not self.consumer:
            return

        self.logger.info("Kafka listener started")

        try:
            while self.is_running:
                try:
                    msg = await asyncio.wait_for(self.consumer.getone(), timeout=0.1)

                    # Skip messages from this instance - publisher handles its own state
                    headers = dict(msg.headers) if msg.headers else {}
                    source = headers.get("source_instance", b"").decode("utf-8")
                    if source == self._instance_id:
                        continue

                    try:
                        event_dict = json.loads(msg.value.decode("utf-8"))
                        event = EventBusEvent.model_validate(event_dict)
                        await self._distribute_event(event.event_type, event)
                    except Exception as e:
                        self.logger.error(f"Error processing Kafka message: {e}")

                except asyncio.TimeoutError:
                    continue
                except KafkaError as e:
                    self.logger.error(f"Consumer error: {e}")
                    continue

        except asyncio.CancelledError:
            self.logger.info("Kafka listener cancelled")
        except Exception as e:
            self.logger.error(f"Fatal error in Kafka listener: {e}")

    def _update_metrics(self, pattern: str) -> None:
        """Update metrics for a pattern (must be called within lock)."""
        if self.metrics:
            count = len(self._pattern_index.get(pattern, set()))
            self.metrics.update_event_bus_subscribers(count, pattern)

    async def get_statistics(self) -> dict[str, Any]:
        """Get event bus statistics."""
        async with self._lock:
            return {
                "patterns": list(self._pattern_index.keys()),
                "total_patterns": len(self._pattern_index),
                "total_subscriptions": len(self._subscriptions),
                "kafka_enabled": self.producer is not None,
                "running": self.is_running,
            }


class EventBusManager:
    """Manages EventBus lifecycle as a singleton."""

    def __init__(self, settings: Settings, logger: logging.Logger, connection_metrics: ConnectionMetrics) -> None:
        self.settings = settings
        self.logger = logger
        self._connection_metrics = connection_metrics
        self._event_bus: Optional[EventBus] = None
        self._lock = asyncio.Lock()

    async def get_event_bus(self) -> EventBus:
        """Get or create the event bus instance."""
        async with self._lock:
            if self._event_bus is None:
                self._event_bus = EventBus(self.settings, self.logger, self._connection_metrics)
                await self._event_bus.__aenter__()
            return self._event_bus

    async def close(self) -> None:
        """Stop and clean up the event bus."""
        async with self._lock:
            if self._event_bus:
                await self._event_bus.aclose()
                self._event_bus = None


async def get_event_bus(request: Request) -> EventBus:
    manager: EventBusManager = request.app.state.event_bus_manager
    return await manager.get_event_bus()
