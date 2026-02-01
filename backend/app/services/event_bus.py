import asyncio
import fnmatch
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.metrics import ConnectionMetrics
from app.domain.events.typed import BaseEvent, DomainEvent, domain_event_adapter


@dataclass
class Subscription:
    """Represents a single event subscription."""

    id: str = field(default_factory=lambda: str(uuid4()))
    pattern: str = ""
    handler: Callable[[DomainEvent], Any] = field(default=lambda _: None)


class EventBus:
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

    Kafka producer/consumer are created and managed by the DI provider.
    EventBus receives them ready to use and only manages its own listener
    task and subscription registry.
    """

    def __init__(
        self,
        producer: AIOKafkaProducer,
        consumer: AIOKafkaConsumer,
        topic: str,
        logger: logging.Logger,
        connection_metrics: ConnectionMetrics,
    ) -> None:
        self.logger = logger
        self.metrics = connection_metrics
        self._producer = producer
        self._consumer = consumer
        self._topic = topic
        self._subscriptions: dict[str, Subscription] = {}  # id -> Subscription
        self._pattern_index: dict[str, set[str]] = {}  # pattern -> set of subscription ids
        self._lock = asyncio.Lock()
        self._instance_id = str(uuid4())  # Unique ID for filtering self-published messages
        asyncio.create_task(self._kafka_listener())

    async def publish(self, event: BaseEvent) -> None:
        """
        Publish a typed event to Kafka for cross-instance distribution.

        Local handlers receive events only from OTHER instances via the Kafka listener.
        Publishers should update their own state directly before calling publish().
        """
        try:
            value = event.model_dump_json().encode("utf-8")
            key = event.event_type.encode("utf-8")
            headers = [("source_instance", self._instance_id.encode("utf-8"))]

            await self._producer.send_and_wait(
                topic=self._topic,
                value=value,
                key=key,
                headers=headers,
            )
        except Exception as e:
            self.logger.error(f"Failed to publish to Kafka: {e}")

    async def subscribe(self, pattern: str, handler: Callable[[DomainEvent], Any]) -> str:
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
            self._subscriptions[subscription.id] = subscription

            if pattern not in self._pattern_index:
                self._pattern_index[pattern] = set()
            self._pattern_index[pattern].add(subscription.id)

            self.metrics.increment_event_bus_subscriptions()

        self.logger.debug(f"Created subscription {subscription.id} for pattern: {pattern}")
        return subscription.id

    async def unsubscribe(self, pattern: str, handler: Callable[[DomainEvent], Any]) -> None:
        """Unsubscribe a specific handler from a pattern."""
        async with self._lock:
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

        del self._subscriptions[subscription_id]

        if pattern in self._pattern_index:
            self._pattern_index[pattern].discard(subscription_id)
            if not self._pattern_index[pattern]:
                del self._pattern_index[pattern]

        self.metrics.decrement_event_bus_subscriptions()
        self.logger.debug(f"Removed subscription {subscription_id} for pattern: {pattern}")

    async def _distribute_event(self, event: DomainEvent) -> None:
        """Distribute event to all matching local subscribers."""
        matching_handlers = await self._find_matching_handlers(event.event_type)

        if not matching_handlers:
            return

        results = await asyncio.gather(
            *(self._invoke_handler(handler, event) for handler in matching_handlers), return_exceptions=True
        )

        for _i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Handler failed for event {event.event_type}: {result}")

    async def _find_matching_handlers(self, event_type: str) -> list[Callable[[DomainEvent], Any]]:
        """Find all handlers matching the event type."""
        async with self._lock:
            handlers: list[Callable[[DomainEvent], Any]] = []
            for pattern, sub_ids in self._pattern_index.items():
                if fnmatch.fnmatch(event_type, pattern):
                    handlers.extend(
                        self._subscriptions[sub_id].handler for sub_id in sub_ids if sub_id in self._subscriptions
                    )
            return handlers

    async def _invoke_handler(self, handler: Callable[[DomainEvent], Any], event: DomainEvent) -> None:
        """Invoke a single handler, handling both sync and async."""
        if asyncio.iscoroutinefunction(handler):
            await handler(event)
        else:
            await asyncio.to_thread(handler, event)

    async def _kafka_listener(self) -> None:
        """Listen for Kafka messages from OTHER instances and distribute to local subscribers.

        Exits naturally when the consumer is stopped by the DI provider.
        """
        self.logger.info("Event bus Kafka listener started")

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(self._consumer.getone(), timeout=0.5)

                    # Skip messages from this instance - publisher handles its own state
                    headers = dict(msg.headers) if msg.headers else {}
                    source = headers.get("source_instance", b"").decode("utf-8")
                    if source == self._instance_id:
                        continue

                    try:
                        event_dict = json.loads(msg.value.decode("utf-8"))
                        event = domain_event_adapter.validate_python(event_dict)
                        await self._distribute_event(event)
                    except Exception as e:
                        self.logger.error(f"Error processing Kafka message: {e}")

                except asyncio.TimeoutError:
                    continue
                except KafkaError as e:
                    self.logger.error(f"Consumer error: {e}")
                    continue
                except Exception:
                    break  # Consumer stopped by DI provider

        except asyncio.CancelledError:
            pass

        self.logger.info("Event bus Kafka listener stopped")
