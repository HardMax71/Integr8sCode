import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from opentelemetry import trace

from app.core.correlation import CorrelationContext
from app.core.metrics.context import get_event_metrics
from app.core.tracing.utils import inject_trace_context
from app.db.repositories.event_repository import EventRepository
from app.domain.enums.events import EventType
from app.domain.events import domain_event_adapter
from app.domain.events.typed import DomainEvent, EventMetadata
from app.events.core import UnifiedProducer
from app.settings import Settings

tracer = trace.get_tracer(__name__)


class KafkaEventService:
    def __init__(
        self,
        event_repository: EventRepository,
        kafka_producer: UnifiedProducer,
        settings: Settings,
        logger: logging.Logger,
    ):
        self.event_repository = event_repository
        self.kafka_producer = kafka_producer
        self.logger = logger
        self.metrics = get_event_metrics()
        self.settings = settings

    async def publish_event(
        self,
        event_type: EventType,
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

            event_metadata = metadata or EventMetadata(
                service_name=self.settings.SERVICE_NAME,
                service_version=self.settings.SERVICE_VERSION,
                correlation_id=correlation_id or str(uuid4()),
            )
            if correlation_id and event_metadata.correlation_id != correlation_id:
                event_metadata = event_metadata.model_copy(update={"correlation_id": correlation_id})

            event_id = str(uuid4())
            timestamp = datetime.now(timezone.utc)

            # Create typed domain event via discriminated union adapter
            event_data = {
                "event_id": event_id,
                "event_type": event_type,
                "event_version": "1.0",
                "timestamp": timestamp,
                "aggregate_id": aggregate_id,
                "metadata": event_metadata,
                **payload,
            }
            domain_event = domain_event_adapter.validate_python(event_data)
            await self.event_repository.store_event(domain_event)

            # Prepare headers
            headers: Dict[str, str] = {
                "event_type": event_type,
                "correlation_id": event_metadata.correlation_id or "",
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
            await self.kafka_producer.produce(domain_event, aggregate_id, headers)
            self.metrics.record_event_published(event_type)
            self.metrics.record_event_processing_duration(time.time() - start_time, event_type)
            self.logger.info("Event published", extra={"event_type": event_type, "event_id": domain_event.event_id})
            return domain_event.event_id

    async def publish_execution_event(
        self,
        event_type: EventType,
        execution_id: str,
        status: str,
        metadata: EventMetadata | None = None,
        error_message: str | None = None,
    ) -> str:
        """Publish execution-related event using provided metadata (no framework coupling)."""
        self.logger.info(
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

        self.logger.info(
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
        event_type: EventType,
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

    async def publish_domain_event(self, event: DomainEvent, key: str | None = None) -> str:
        """Publish a pre-built DomainEvent to Kafka and store an audit copy."""
        with tracer.start_as_current_span("publish_domain_event") as span:
            span.set_attribute("event.type", event.event_type)
            if event.aggregate_id:
                span.set_attribute("aggregate.id", event.aggregate_id)

            start_time = time.time()
            await self.event_repository.store_event(event)

            headers: Dict[str, str] = {
                "event_type": event.event_type,
                "correlation_id": event.metadata.correlation_id or "",
                "service": event.metadata.service_name,
            }
            span_context = span.get_span_context()
            if span_context.is_valid:
                headers["trace_id"] = f"{span_context.trace_id:032x}"
                headers["span_id"] = f"{span_context.span_id:016x}"
            headers = inject_trace_context(headers)

            await self.kafka_producer.produce(event, key or event.aggregate_id, headers)
            self.metrics.record_event_published(event.event_type)
            self.metrics.record_event_processing_duration(time.time() - start_time, event.event_type)
            self.logger.info("Domain event published", extra={"event_id": event.event_id})
            return event.event_id

    async def close(self) -> None:
        """Close event service resources"""
        await self.kafka_producer.aclose()
