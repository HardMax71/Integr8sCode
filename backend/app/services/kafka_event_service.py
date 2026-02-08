import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from opentelemetry import trace

from app.core.correlation import CorrelationContext
from app.core.metrics import EventMetrics
from app.domain.enums import EventType
from app.domain.events import DomainEvent, DomainEventAdapter, EventMetadata
from app.events.core import UnifiedProducer
from app.settings import Settings

tracer = trace.get_tracer(__name__)


class KafkaEventService:
    def __init__(
        self,
        kafka_producer: UnifiedProducer,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
    ):
        self.kafka_producer = kafka_producer
        self.logger = logger
        self.metrics = event_metrics
        self.settings = settings

    async def publish_event(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        aggregate_id: str | None,
        correlation_id: str | None = None,
        metadata: EventMetadata | None = None,
    ) -> str:
        """
        Build a typed DomainEvent from parameters and publish to Kafka.

        The producer persists the event to MongoDB before publishing.
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
            domain_event = DomainEventAdapter.validate_python(event_data)

            await self.kafka_producer.produce(event_to_produce=domain_event, key=aggregate_id or domain_event.event_id)
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
        """Publish a pre-built DomainEvent to Kafka.

        The producer persists the event to MongoDB before publishing.
        """
        with tracer.start_as_current_span("publish_domain_event") as span:
            span.set_attribute("event.type", event.event_type)
            if event.aggregate_id:
                span.set_attribute("aggregate.id", event.aggregate_id)

            start_time = time.time()

            await self.kafka_producer.produce(event_to_produce=event, key=key or event.aggregate_id or event.event_id)
            self.metrics.record_event_published(event.event_type)
            self.metrics.record_event_processing_duration(time.time() - start_time, event.event_type)
            self.logger.info("Domain event published", extra={"event_id": event.event_id})
            return event.event_id
