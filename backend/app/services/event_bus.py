"""Event Bus - stateless pub/sub service.

Distributed event bus for cross-instance communication via Kafka.
No lifecycle management - receives ready-to-use producer from DI.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from pydantic import BaseModel, ConfigDict

from app.core.metrics import ConnectionMetrics
from app.domain.enums.kafka import KafkaTopic
from app.settings import Settings


class EventBusEvent(BaseModel):
    """Represents an event on the event bus."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    timestamp: datetime
    payload: dict[str, object]


@dataclass
class Subscription:
    """Represents a single event subscription."""

    id: str = field(default_factory=lambda: str(uuid4()))
    pattern: str = ""
    handler: object = field(default=None)


class EventBus:
    """Stateless event bus - pure pub/sub service."""

    def __init__(
        self,
        producer: AIOKafkaProducer,
        settings: Settings,
        logger: logging.Logger,
        connection_metrics: ConnectionMetrics,
    ) -> None:
        self._producer = producer
        self._settings = settings
        self._logger = logger
        self._metrics = connection_metrics
        self._subscriptions: dict[str, Subscription] = {}
        self._pattern_index: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._topic = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.EVENT_BUS_STREAM}"
        self._instance_id = str(uuid4())

    async def publish(self, event_type: str, data: dict[str, object]) -> None:
        """Publish an event to Kafka for cross-instance distribution."""
        event = EventBusEvent(
            id=str(uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=data,
        )

        try:
            await self._producer.send_and_wait(
                topic=self._topic,
                value=event.model_dump_json().encode(),
                key=event_type.encode(),
                headers=[("source_instance", self._instance_id.encode())],
            )
        except Exception as e:
            self._logger.error(f"Failed to publish to Kafka: {e}")

    async def subscribe(self, pattern: str, handler: object) -> str:
        """Subscribe to events matching a pattern. Returns subscription ID."""
        subscription = Subscription(pattern=pattern, handler=handler)

        async with self._lock:
            self._subscriptions[subscription.id] = subscription
            if pattern not in self._pattern_index:
                self._pattern_index[pattern] = set()
            self._pattern_index[pattern].add(subscription.id)
            self._metrics.update_event_bus_subscribers(len(self._pattern_index[pattern]), pattern)

        return subscription.id

    async def unsubscribe(self, pattern: str, handler: object) -> None:
        """Unsubscribe a handler from a pattern."""
        async with self._lock:
            for sub_id, sub in list(self._subscriptions.items()):
                if sub.pattern == pattern and sub.handler == handler:
                    del self._subscriptions[sub_id]
                    self._pattern_index[pattern].discard(sub_id)
                    if not self._pattern_index[pattern]:
                        del self._pattern_index[pattern]
                        self._metrics.update_event_bus_subscribers(0, pattern)
                    else:
                        self._metrics.update_event_bus_subscribers(len(self._pattern_index[pattern]), pattern)
                    return

    async def handle_kafka_message(self, raw_message: bytes, headers: dict[str, str]) -> None:
        """Handle a Kafka message. Skips messages from this instance."""
        if headers.get("source_instance") == self._instance_id:
            return

        try:
            event = EventBusEvent.model_validate(json.loads(raw_message))
            await self._distribute_event(event)
        except Exception as e:
            self._logger.error(f"Error processing Kafka message: {e}")

    async def _distribute_event(self, event: EventBusEvent) -> None:
        """Distribute event to matching local subscribers."""
        async with self._lock:
            handlers = [
                self._subscriptions[sub_id].handler
                for pattern, sub_ids in self._pattern_index.items()
                if fnmatch.fnmatch(event.event_type, pattern)
                for sub_id in sub_ids
                if sub_id in self._subscriptions
            ]

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)  # type: ignore[operator]
            except Exception as e:
                self._logger.error(f"Handler failed for {event.event_type}: {e}")
