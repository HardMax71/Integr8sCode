import time
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from opentelemetry import trace

from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.core.metrics.context import get_event_metrics
from app.core.tracing.utils import inject_trace_context
from app.db.repositories.event_repository import EventRepository
from app.domain.enums.events import EventType
from app.domain.events import Event
from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.mappings import get_event_class_for_type
from app.settings import get_settings

tracer = trace.get_tracer(__name__)


class KafkaEventService:
    def __init__(self, event_repository: EventRepository, kafka_producer: UnifiedProducer):
        self.event_repository = event_repository
        self.kafka_producer = kafka_producer
        self.metrics = get_event_metrics()
        self.settings = get_settings()

    async def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        aggregate_id: str | None,
        correlation_id: str | None = None,
        metadata: EventMetadata | None = None,
    ) -> str:
        """
        Publish an event to Kafka and store an audit copy via the repository

        Args:
            event_type: Type of event (e.g., "execution.requested")
            payload: Event-specific data
            aggregate_id: ID of the aggregate root
            correlation_id: ID for correlating related events
            metadata: Event metadata (service/user/trace/IP). If None, service fills minimal defaults.

        Returns:
            Event ID of published event
        """
        with tracer.start_as_current_span("publish_event") as span:
            span.set_attribute("event.type", event_type)
            if aggregate_id is not None:
                span.set_attribute("aggregate.id", aggregate_id)

            start_time = time.time()

            if not correlation_id:
                correlation_id = CorrelationContext.get_correlation_id()

            # Create or enrich event metadata
            event_metadata = metadata or EventMetadata(
                service_name=self.settings.SERVICE_NAME,
                service_version=self.settings.SERVICE_VERSION,
            )
            event_metadata = event_metadata.with_correlation(correlation_id or str(uuid4()))

            # Create event
            event_id = str(uuid4())
            timestamp = datetime.now(timezone.utc)
            # Create domain event (using the unified EventMetadata)
            event = Event(
                event_id=event_id,
                event_type=event_type,
                event_version="1.0",
                timestamp=timestamp,
                aggregate_id=aggregate_id,
                metadata=event_metadata,
                payload=payload,
            )
            _ = await self.event_repository.store_event(event)

            # Get event class and create proper event instance
            event_type_enum = EventType(event_type)
            event_class = get_event_class_for_type(event_type_enum)
            if not event_class:
                raise ValueError(f"No event class found for event type: {event_type}")

            # Create proper event instance with all required fields
            event_data = {
                "event_id": event.event_id,
                "event_type": event_type_enum,
                "event_version": "1.0",
                "timestamp": timestamp,
                "aggregate_id": aggregate_id,
                "metadata": event_metadata,
                **payload,  # Include event-specific payload fields
            }

            # Create the typed event instance
            kafka_event = event_class(**event_data)

            # Prepare headers (all values must be strings for UnifiedProducer)
            headers: Dict[str, str] = {
                "event_type": event_type,
                "correlation_id": event.correlation_id or "",
                "service": event_metadata.service_name,
            }

            # Add trace context
            span_context = span.get_span_context()
            if span_context.is_valid:
                headers["trace_id"] = f"{span_context.trace_id:032x}"
                headers["span_id"] = f"{span_context.span_id:016x}"

            # Inject W3C trace context for downstream consumers
            headers = inject_trace_context(headers)

            # Publish to Kafka
            await self.kafka_producer.produce(event_to_produce=kafka_event, key=aggregate_id, headers=headers)

            self.metrics.record_event_published(event_type)

            # Record processing duration
            duration = time.time() - start_time
            self.metrics.record_event_processing_duration(duration, event_type)

            logger.info(
                "Event published",
                extra={
                    "event_type": event_type,
                    "event_id": kafka_event.event_id,
                    "topic": getattr(kafka_event, "topic", "unknown"),
                },
            )

            return kafka_event.event_id

    async def publish_execution_event(
        self,
        event_type: str,
        execution_id: str,
        status: str,
        metadata: EventMetadata | None = None,
        error_message: str | None = None,
    ) -> str:
        """Publish execution-related event using provided metadata (no framework coupling)."""
        logger.info(
            "Publishing execution event",
            extra={
                "event_type": event_type,
                "execution_id": execution_id,
                "status": status,
            },
        )

        payload = {"execution_id": execution_id, "status": status}

        if error_message:
            payload["error_message"] = error_message

        event_id = await self.publish_event(
            event_type=event_type,
            payload=payload,
            aggregate_id=execution_id,
            metadata=metadata,
        )

        logger.info(
            "Execution event published successfully",
            extra={
                "event_type": event_type,
                "execution_id": execution_id,
                "event_id": event_id,
            },
        )

        return event_id

    async def publish_pod_event(
        self,
        event_type: str,
        pod_name: str,
        execution_id: str,
        namespace: str = "integr8scode",
        status: str | None = None,
        metadata: EventMetadata | None = None,
    ) -> str:
        """Publish pod-related event"""
        payload = {"pod_name": pod_name, "execution_id": execution_id, "namespace": namespace}

        if status:
            payload["status"] = status

        return await self.publish_event(
            event_type=event_type,
            payload=payload,
            aggregate_id=execution_id,
            metadata=metadata,
        )

    async def close(self) -> None:
        """Close event service resources"""
        await self.kafka_producer.stop()
