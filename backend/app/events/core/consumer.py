"""Unified Kafka consumer - pure message handler.

Handles deserialization, dispatch, and metrics for Kafka messages.
No lifecycle, no properties, no state - just handle().
Worker gets AIOKafkaConsumer directly from DI.
"""

from __future__ import annotations

import logging

from aiokafka import ConsumerRecord
from opentelemetry.trace import SpanKind

from app.core.metrics import EventMetrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer
from app.domain.events.typed import DomainEvent
from app.events.schema.schema_registry import SchemaRegistryManager

from .dispatcher import EventDispatcher


class UnifiedConsumer:
    """Pure message handler - deserialize, dispatch, record metrics."""

    def __init__(
        self,
        event_dispatcher: EventDispatcher,
        schema_registry: SchemaRegistryManager,
        logger: logging.Logger,
        event_metrics: EventMetrics,
        group_id: str,
    ) -> None:
        self._dispatcher = event_dispatcher
        self._schema_registry = schema_registry
        self._logger = logger
        self._event_metrics = event_metrics
        self._group_id = group_id

    async def handle(self, msg: ConsumerRecord) -> DomainEvent | None:
        """Handle a Kafka message - deserialize, dispatch, record metrics."""
        if msg.value is None:
            return None

        event = await self._schema_registry.deserialize_event(msg.value, msg.topic)
        headers = {k: v.decode() for k, v in msg.headers}

        with get_tracer().start_as_current_span(
            name="kafka.consume",
            context=extract_trace_context(headers),
            kind=SpanKind.CONSUMER,
            attributes={
                EventAttributes.KAFKA_TOPIC: msg.topic,
                EventAttributes.KAFKA_PARTITION: msg.partition,
                EventAttributes.KAFKA_OFFSET: msg.offset,
                EventAttributes.EVENT_TYPE: event.event_type,
                EventAttributes.EVENT_ID: event.event_id,
            },
        ):
            try:
                await self._dispatcher.dispatch(event)
                self._event_metrics.record_kafka_message_consumed(msg.topic, self._group_id)
            except Exception as e:
                self._logger.error(f"Dispatch error: {event.event_type}: {e}")
                self._event_metrics.record_kafka_consumption_error(msg.topic, self._group_id, type(e).__name__)
                raise

        return event
