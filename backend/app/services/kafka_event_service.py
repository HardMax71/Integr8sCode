"""Kafka-based event service for publishing and storing events"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Request
from opentelemetry import trace

from app.config import get_settings
from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.core.metrics import EVENT_PROCESSING_DURATION, EVENT_PUBLISHED
from app.db.mongodb import DatabaseManager
from app.db.repositories.event_repository import EventRepository, get_event_repository
from app.domain.events import Event
from app.domain.events import EventMetadata as DomainEventMetadata
from app.events.core.mapping import get_topic_name
from app.events.core.producer import UnifiedProducer, get_producer
from app.schemas_pydantic.events import EventMetadata
from app.schemas_pydantic.user import User

tracer = trace.get_tracer(__name__)


class KafkaEventService:
    """Service for handling event publishing to Kafka and storage"""

    def __init__(
            self,
            event_repository: EventRepository,
            kafka_producer: Optional[UnifiedProducer] = None
    ):
        self.event_repository = event_repository
        self.kafka_producer = kafka_producer
        self._initialized = False
        self.settings = get_settings()

    async def initialize(self) -> None:
        """Initialize event service"""
        if not self._initialized:
            await self.event_repository.initialize()

            # Initialize Kafka producer if not provided
            if not self.kafka_producer:
                self.kafka_producer = await get_producer()

            self._initialized = True
            logger.info("Kafka event service initialized")

    async def publish_event(
            self,
            event_type: str,
            payload: Dict[str, Any],
            aggregate_id: Optional[str] = None,
            correlation_id: Optional[str] = None,
            causation_id: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            user: Optional[User] = None,
            request: Optional[Request] = None
    ) -> str:
        """
        Publish an event to Kafka and store in MongoDB
        
        Args:
            event_type: Type of event (e.g., "execution.requested")
            payload: Event-specific data
            aggregate_id: ID of the aggregate root
            correlation_id: ID for correlating related events
            causation_id: ID of the event that caused this event
            metadata: Additional metadata
            user: Current user (if available)
            request: HTTP request (for extracting IP, user agent)
            
        Returns:
            Event ID of published event
        """
        with tracer.start_as_current_span("publish_event") as span:
            span.set_attribute("event.type", event_type)
            span.set_attribute("aggregate.id", aggregate_id or "none")

            import time
            start_time = time.time()

            try:
                # Create event metadata
                event_metadata = self._create_metadata(metadata, user, request)

                # Get correlation ID from context if not provided
                if not correlation_id:
                    correlation_id = CorrelationContext.get_correlation_id()

                # Create event
                event_id = str(uuid4())
                timestamp = datetime.now(timezone.utc)
                domain_metadata = DomainEventMetadata(
                    service_name=event_metadata.service_name,
                    service_version=event_metadata.service_version,
                    user_id=event_metadata.user_id,
                    ip_address=event_metadata.ip_address,
                    user_agent=event_metadata.user_agent,
                    session_id=event_metadata.session_id
                )
                # Create domain event
                event = Event(
                    event_id=event_id,
                    event_type=event_type,
                    event_version="1.0",
                    timestamp=timestamp,
                    aggregate_id=aggregate_id,
                    correlation_id=correlation_id or str(uuid4()),
                    causation_id=causation_id,
                    metadata=domain_metadata,
                    payload=payload
                )
                _ = await self.event_repository.store_event(event)

                # Determine Kafka topic
                topic = self._get_topic_for_event(event_type)

                # Prepare Kafka event
                kafka_event = {
                    "event_id": event.event_id,
                    "event_type": event_type,
                    "timestamp": int(timestamp.timestamp() * 1000),
                    "version": 1,
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                    "aggregate_id": aggregate_id,
                    "metadata": {
                        "user_id": event_metadata.user_id,
                        "service_name": event_metadata.service_name,
                        "service_version": event_metadata.service_version,
                        "ip_address": event_metadata.ip_address,
                        "user_agent": event_metadata.user_agent,
                        "session_id": event_metadata.session_id
                    },
                    **payload  # Include payload fields
                }

                # Prepare headers
                headers: Dict[str, str | bytes] = {
                    "event_type": event_type,
                    "correlation_id": event.correlation_id or "",
                    "service": domain_metadata.service_name
                }

                # Add trace context
                span_context = span.get_span_context()
                if span_context.is_valid:
                    headers["trace_id"] = f"{span_context.trace_id:032x}"
                    headers["span_id"] = f"{span_context.span_id:016x}"

                # Publish to Kafka
                if self.kafka_producer:
                    _ = await self.kafka_producer.send_event(
                        event=kafka_event,
                        topic=topic,
                        key=aggregate_id or event.event_id,
                        headers=headers
                    )
                else:
                    logger.warning("Kafka producer not initialized, event only stored in MongoDB")

                # result is a DeliveryReport object if successful

                # Record metrics
                # Extract aggregate type from aggregate_id (e.g., "user_settings_123" -> "user_settings")
                if aggregate_id and '_' in aggregate_id:
                    # Split and rejoin all parts except the last one (the ID)
                    parts = aggregate_id.split('_')
                    aggregate_type = '_'.join(parts[:-1]) if len(parts) > 1 else parts[0]
                else:
                    aggregate_type = "unknown"
                EVENT_PUBLISHED.labels(event_type=event_type, aggregate_type=aggregate_type).inc()

                duration = time.time() - start_time
                EVENT_PROCESSING_DURATION.labels(
                    event_type=event_type
                ).observe(duration)

                logger.info(
                    f"Event published: type={event_type}, id={event.event_id}, "
                    f"correlation_id={event.correlation_id}, topic={topic}"
                )

                return event.event_id

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
            event_types: Optional[List[str]] = None,
            since: Optional[datetime] = None,
            until: Optional[datetime] = None,
            limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get events for an aggregate"""
        events = await self.event_repository.get_events_by_aggregate(
            aggregate_id=aggregate_id,
            event_types=event_types,
            limit=limit
        )
        return [event.to_dict() for event in events]

    async def get_events_by_correlation(
            self,
            correlation_id: str,
            limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all events with same correlation ID"""
        events = await self.event_repository.get_events_by_correlation(
            correlation_id=correlation_id,
            limit=limit
        )
        return [event.to_dict() for event in events]

    async def publish_execution_event(
            self,
            event_type: str,
            execution_id: str,
            status: str,
            metadata: Optional[Dict[str, Any]] = None,
            error_message: Optional[str] = None,
            user: Optional[User] = None,
            request: Optional[Request] = None
    ) -> str:
        """Publish execution-related event"""
        payload = {
            "execution_id": execution_id,
            "status": status
        }

        if error_message:
            payload["error_message"] = error_message

        # Add any extra metadata to payload
        if metadata:
            payload.update(metadata)

        return await self.publish_event(
            event_type=event_type,
            payload=payload,
            aggregate_id=execution_id,
            metadata=metadata,
            user=user,
            request=request
        )

    async def publish_pod_event(
            self,
            event_type: str,
            pod_name: str,
            execution_id: str,
            namespace: str = "default",
            status: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            user: Optional[User] = None,
            request: Optional[Request] = None
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
            user=user,
            request=request
        )

    async def get_execution_events(
            self,
            execution_id: str,
            limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all events for an execution"""
        events = await self.event_repository.get_execution_events(execution_id)
        return [event.to_dict() for event in events]

    def _create_metadata(
            self,
            metadata: Optional[Dict[str, Any]],
            user: Optional[User],
            request: Optional[Request]
    ) -> EventMetadata:
        """Create event metadata from context"""
        meta_dict = metadata or {}

        # Add user info
        if user:
            meta_dict["user_id"] = str(user.user_id)

        # Add request info
        if request:
            meta_dict["ip_address"] = request.client.host if request.client else None
            meta_dict["user_agent"] = request.headers.get("user-agent")

        # Add service info
        meta_dict["service_name"] = self.settings.SERVICE_NAME
        meta_dict["service_version"] = self.settings.SERVICE_VERSION

        # Get session ID from correlation context
        meta_dict["session_id"] = CorrelationContext.get_correlation_id()

        return EventMetadata(**meta_dict)

    def _get_topic_for_event(self, event_type: str) -> str:
        """Determine Kafka topic for event type"""
        return get_topic_name(event_type)

    async def close(self) -> None:
        """Close event service resources"""
        if self.kafka_producer:
            await self.kafka_producer.stop()


class KafkaEventServiceManager:
    """Manages Kafka event service lifecycle"""

    def __init__(self) -> None:
        self._service: Optional[KafkaEventService] = None

    async def get_service(
            self,
            db_manager: DatabaseManager,
            kafka_producer: Optional[UnifiedProducer] = None
    ) -> KafkaEventService:
        """Get or create event service instance"""
        if self._service is None:
            event_repository = get_event_repository(db_manager)
            self._service = KafkaEventService(event_repository, kafka_producer)
            await self._service.initialize()
        return self._service

    async def close(self) -> None:
        """Close event service"""
        if self._service:
            await self._service.close()
            self._service = None


async def get_event_service(request: Request) -> KafkaEventService:
    """FastAPI dependency to get event service"""
    if hasattr(request.app.state, "event_service_manager"):
        manager: KafkaEventServiceManager = request.app.state.event_service_manager
        db_manager = request.app.state.db_manager
        return await manager.get_service(db_manager)

    # Fallback for testing
    raise RuntimeError("Event service not initialized")
