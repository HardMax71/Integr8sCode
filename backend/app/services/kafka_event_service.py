import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import Request
from opentelemetry import trace

from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.core.metrics.context import get_event_metrics
from app.db.repositories.event_repository import EventRepository
from app.domain.enums.events import EventType
from app.domain.events import Event
from app.events.core.producer import UnifiedProducer
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.mappings import get_event_class_for_type
from app.settings import get_settings

tracer = trace.get_tracer(__name__)


class KafkaEventService:
    """Service for handling event publishing to Kafka and storage"""

    def __init__(
            self,
            event_repository: EventRepository,
            kafka_producer: UnifiedProducer
    ):
        self.event_repository = event_repository
        self.kafka_producer = kafka_producer
        self.metrics = get_event_metrics()
        self.settings = get_settings()

    async def publish_event(
            self,
            event_type: str,
            payload: Dict[str, Any],
            aggregate_id: str | None = None,
            correlation_id: str | None = None,
            metadata: Dict[str, Any] | None = None,
            user_id: str | None = None,
            request: Request | None = None
    ) -> str:
        """
        Publish an event to Kafka and store in MongoDB
        
        Args:
            event_type: Type of event (e.g., "execution.requested")
            payload: Event-specific data
            aggregate_id: ID of the aggregate root
            correlation_id: ID for correlating related events
            metadata: Additional metadata
            user: Current user (if available)
            request: HTTP request (for extracting IP, user agent)
            
        Returns:
            Event ID of published event
        """
        with tracer.start_as_current_span("publish_event") as span:
            span.set_attribute("event.type", event_type)
            span.set_attribute("aggregate.id", aggregate_id or "none")

            start_time = time.time()

            try:
                # Get correlation ID from context if not provided
                if not correlation_id:
                    correlation_id = CorrelationContext.get_correlation_id()

                # Create event metadata with correlation ID
                event_metadata = self._create_metadata(metadata, user_id, request)
                # Ensure correlation_id is in metadata
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
                    payload=payload
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
                    **payload  # Include event-specific payload fields
                }

                # Create the typed event instance
                kafka_event = event_class(**event_data)

                # Prepare headers (all values must be strings for UnifiedProducer)
                headers: Dict[str, str] = {
                    "event_type": event_type,
                    "correlation_id": event.correlation_id or "",
                    "service": event_metadata.service_name
                }

                # Add trace context
                span_context = span.get_span_context()
                if span_context.is_valid:
                    headers["trace_id"] = f"{span_context.trace_id:032x}"
                    headers["span_id"] = f"{span_context.span_id:016x}"

                # Publish to Kafka
                await self.kafka_producer.produce(
                    event_to_produce=kafka_event,
                    key=aggregate_id or event.event_id,
                    headers=headers
                )

                self.metrics.record_event_published(event_type)

                # Record processing duration
                duration = time.time() - start_time
                self.metrics.record_event_processing_duration(duration, event_type)

                logger.info(
                    f"Event published: type={kafka_event}, id={kafka_event.event_id}, "
                    f"topic={kafka_event.topic}"
                )

                return kafka_event.event_id

            except Exception as e:
                logger.error(f"Error publishing event: {e}")
                span.record_exception(e)
                raise

    async def publish_batch(
            self,
            events: List[Dict[str, Any]]
    ) -> List[str]:
        """Publish multiple events"""
        event_ids = []

        for event_data in events:
            event_id = await self.publish_event(**event_data)
            event_ids.append(event_id)

        return event_ids

    async def get_events_by_aggregate(
            self,
            aggregate_id: str,
            event_types: List[str] | None = None,
            limit: int = 100
    ) -> list[Event]:
        """Get events for an aggregate (domain)."""
        events = await self.event_repository.get_events_by_aggregate(
            aggregate_id=aggregate_id,
            event_types=event_types,
            limit=limit
        )
        return events

    async def get_events_by_correlation(
            self,
            correlation_id: str,
            limit: int = 100
    ) -> list[Event]:
        """Get all events with same correlation ID (domain)."""
        events = await self.event_repository.get_events_by_correlation(
            correlation_id=correlation_id,
            limit=limit
        )
        return events

    async def publish_execution_event(
            self,
            event_type: str,
            execution_id: str,
            status: str,
            metadata: Dict[str, Any] | None = None,
            error_message: str | None = None,
            user_id: str | None = None,
            request: Request | None = None
    ) -> str:
        """Publish execution-related event"""
        logger.info(
            "Publishing execution event",
            extra={
                "event_type": event_type,
                "execution_id": execution_id,
                "status": status,
                "user_id": user_id,
            }
        )

        payload = {
            "execution_id": execution_id,
            "status": status
        }

        if error_message:
            payload["error_message"] = error_message

        # Add any extra metadata to payload
        if metadata:
            payload.update(metadata)

        event_id = await self.publish_event(
            event_type=event_type,
            payload=payload,
            aggregate_id=execution_id,
            metadata=metadata,
            user_id=user_id,
            request=request
        )

        logger.info(
            "Execution event published successfully",
            extra={
                "event_type": event_type,
                "execution_id": execution_id,
                "event_id": event_id,
            }
        )

        return event_id

    async def publish_pod_event(
            self,
            event_type: str,
            pod_name: str,
            execution_id: str,
            namespace: str = "integr8scode",
            status: str | None = None,
            metadata: Dict[str, Any] | None = None,
            user_id: str | None = None,
            request: Request | None = None
    ) -> str:
        """Publish pod-related event"""
        payload = {
            "pod_name": pod_name,
            "execution_id": execution_id,
            "namespace": namespace
        }

        if status:
            payload["status"] = status

        # Add any extra metadata to payload
        if metadata:
            payload.update(metadata)

        return await self.publish_event(
            event_type=event_type,
            payload=payload,
            aggregate_id=execution_id,
            metadata=metadata,
            user_id=user_id,
            request=request
        )

    async def get_execution_events(
            self,
            execution_id: str,
            limit: int = 100
    ) -> list[Event]:
        """Get all events for an execution (domain)."""
        events = await self.event_repository.get_execution_events(execution_id)
        return events

    def _create_metadata(
            self,
            metadata: Dict[str, Any] | None,
            user_id: str | None,
            request: Request | None
    ) -> EventMetadata:
        """Create event metadata from context"""
        meta_dict = metadata or {}

        # Add user info
        if user_id:
            meta_dict["user_id"] = str(user_id)

        # Add request info
        if request:
            # Get client IP directly (safe, no DNS lookup)
            meta_dict["ip_address"] = request.client.host if request.client else None
            meta_dict["user_agent"] = request.headers.get("user-agent")

        # Add service info
        meta_dict["service_name"] = self.settings.SERVICE_NAME
        meta_dict["service_version"] = self.settings.SERVICE_VERSION

        # Get session ID from correlation context
        meta_dict["session_id"] = CorrelationContext.get_correlation_id()

        return EventMetadata(**meta_dict)

    async def close(self) -> None:
        """Close event service resources"""
        await self.kafka_producer.stop()
