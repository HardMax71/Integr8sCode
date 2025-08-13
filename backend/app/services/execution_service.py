"""
Unified event-driven execution service for code execution orchestration.

This service handles code execution requests by publishing events to Kafka,
enabling a distributed, scalable architecture where workers process executions
independently. It maintains backward compatibility while providing a modern,
event-driven approach to execution management.
"""

import asyncio
from contextlib import suppress
from datetime import datetime
from time import time
from typing import Any, TypeAlias
from uuid import UUID, uuid4

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.core.correlation import CorrelationContext
from app.core.exceptions import IntegrationException
from app.core.logging import logger
from app.core.metrics import (
    ACTIVE_EXECUTIONS,
    ERROR_COUNTER,
    QUEUE_DEPTH,
    QUEUE_WAIT_TIME,
)
from app.db.repositories.execution_repository import (
    ExecutionRepository,
    get_execution_repository,
)
from app.events.core.producer import UnifiedProducer, get_producer
from app.events.store.event_store import EventStore, get_event_store
from app.runtime_registry import RUNTIME_REGISTRY, RuntimeConfig
from app.schemas_avro.event_schemas import (
    BaseEvent,
    EventMetadata,
    EventType,
    ExecutionCancelledEvent,
    ExecutionRequestedEvent,
    get_topic_for_event,
)
from app.schemas_pydantic.execution import (
    ExecutionCreate,
    ExecutionInDB,
    ExecutionStatus,
    ExecutionUpdate,
)
from app.schemas_pydantic.user import User

# Type aliases for better readability
UserId: TypeAlias = str
EventFilter: TypeAlias = list[EventType] | None
TimeRange: TypeAlias = tuple[datetime | None, datetime | None]
ExecutionQuery: TypeAlias = dict[str, Any]
ExecutionStats: TypeAlias = dict[str, Any]


class ExecutionServiceError(Exception):
    """Base exception for execution service errors."""
    pass


class RuntimeNotSupportedError(ExecutionServiceError):
    """Raised when requested runtime is not supported."""
    pass


class EventPublishError(ExecutionServiceError):
    """Raised when event publishing fails."""
    pass


class ExecutionNotFoundError(ExecutionServiceError):
    """Raised when execution is not found."""
    pass


class ExecutionService:
    """
    Unified execution service that orchestrates code execution through events.
    
    This service creates execution records and publishes events to Kafka,
    where specialized workers handle the actual execution in isolated environments.
    Results are updated asynchronously through event processing.
    """

    def __init__(
            self,
            execution_repo: ExecutionRepository,
            producer: UnifiedProducer | None = None,
            event_store: EventStore | None = None,
            settings: Settings | None = None,
    ) -> None:
        """
        Initialize execution service.
        
        Args:
            execution_repo: Repository for execution data persistence.
            producer: Kafka producer for publishing events.
            event_store: Event store for event persistence.
            settings: Application settings.
        """
        self.execution_repo = execution_repo
        self.producer = producer
        self.event_store = event_store
        self.settings = settings or get_settings()
        self._initialized = False
        self._lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """Ensure required services are initialized."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:  # Double-check pattern
                return

            if not self.producer:
                self.producer = await get_producer()
            if not self.event_store:
                self.event_store = get_event_store()
            self._initialized = True

    async def get_k8s_resource_limits(self) -> dict[str, Any]:
        """
        Get Kubernetes resource limits and configuration.
        
        Returns:
            Dictionary containing resource limits and supported runtimes.
        """
        return {
            "cpu_limit": self.settings.K8S_POD_CPU_LIMIT,
            "memory_limit": self.settings.K8S_POD_MEMORY_LIMIT,
            "cpu_request": self.settings.K8S_POD_CPU_REQUEST,
            "memory_request": self.settings.K8S_POD_MEMORY_REQUEST,
            "execution_timeout": self.settings.K8S_POD_EXECUTION_TIMEOUT,
            "supported_runtimes": self.settings.SUPPORTED_RUNTIMES,
        }

    async def get_example_scripts(self) -> dict[str, str]:
        """
        Get example scripts for all supported languages.
        
        Returns:
            Dictionary mapping language to example script.
        """
        return self.settings.EXAMPLE_SCRIPTS

    def _validate_runtime(self, lang: str, lang_version: str) -> RuntimeConfig:
        """
        Validate language and version are supported.
        
        Args:
            lang: Programming language.
            lang_version: Language version.
            
        Returns:
            RuntimeConfig for the validated runtime.
            
        Raises:
            RuntimeNotSupportedError: If runtime is not supported.
        """
        # Check if language is supported
        if lang not in self.settings.SUPPORTED_RUNTIMES:
            supported = list(self.settings.SUPPORTED_RUNTIMES.keys())
            raise RuntimeNotSupportedError(
                f"Language '{lang}' not supported. Supported: {supported}"
            )

        # Check if version is supported
        supported_versions = self.settings.SUPPORTED_RUNTIMES[lang]
        if lang_version not in supported_versions:
            raise RuntimeNotSupportedError(
                f"Version '{lang_version}' not supported for {lang}. "
                f"Supported: {supported_versions}"
            )

        # Validate runtime registry has configuration
        if lang not in RUNTIME_REGISTRY or lang_version not in RUNTIME_REGISTRY[lang]:
            raise RuntimeNotSupportedError(
                f"Runtime configuration missing for {lang} {lang_version}"
            )

        return RUNTIME_REGISTRY[lang][lang_version]

    def _extract_request_metadata(
            self,
            request: Request | None
    ) -> tuple[str | None, str | None]:
        """
        Extract client IP and user agent from request.
        
        Args:
            request: FastAPI request object.
            
        Returns:
            Tuple of (client_ip, user_agent).
        """
        if not request:
            return None, None

        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        return client_ip, user_agent

    def _extract_user_info(
            self,
            user: User | None,
            request: Request | None
    ) -> tuple[str | None, str | None]:
        """
        Extract user ID and session ID from user object and request.
        
        Args:
            user: User object.
            request: FastAPI request object.
            
        Returns:
            Tuple of (user_id, session_id).
        """
        user_id = None
        session_id = None

        # Extract from user object
        if user:
            user_id = getattr(user, 'user_id', None) or getattr(user, 'id', None)
            if user_id:
                user_id = str(user_id)

        # Extract from request
        if request:
            session_id = request.headers.get("x-session-id")
            if not user_id:
                # Try to get user_id from request state
                user_id = getattr(request.state, 'user_id', None)
                if user_id:
                    user_id = str(user_id)

        return user_id, session_id

    def _create_event_metadata(
            self,
            user_id: str | None = None,
            session_id: str | None = None,
            client_ip: str | None = None,
            user_agent: str | None = None,
    ) -> EventMetadata:
        """
        Create standardized event metadata.
        
        Args:
            user_id: User identifier.
            session_id: Session identifier.
            client_ip: Client IP address.
            user_agent: User agent string.
            
        Returns:
            EventMetadata instance.
        """
        # Get or generate correlation ID
        correlation_id = CorrelationContext.get_correlation_id()
        if not correlation_id:
            correlation_id = f"exec_{uuid4().hex[:12]}"

        # Convert correlation ID to UUID format
        # Handle various correlation ID formats
        clean_id = correlation_id.replace("req_", "").replace("exec_", "").split("_")[0][:32]
        correlation_uuid = str(UUID(clean_id.ljust(32, '0')))

        return EventMetadata(
            correlation_id=correlation_uuid,
            service_name="execution-service",
            service_version="2.0.0",
            user_id=user_id,
            session_id=session_id,
            ip_address=client_ip,
            user_agent=user_agent,
        )

    async def execute_script(
            self,
            script: str,
            lang: str = "python",
            lang_version: str = "3.11",
            user: User | None = None,
            request: Request | None = None,
            priority: int = 5,
            timeout_override: int | None = None,
    ) -> ExecutionInDB:
        """
        Execute a script by creating an execution record and publishing an event.
        
        Args:
            script: The code to execute.
            lang: Programming language.
            lang_version: Language version.
            user: User object (for backward compatibility).
            request: FastAPI request object.
            priority: Execution priority (1-10, lower is higher priority).
            timeout_override: Override default timeout in seconds.
            
        Returns:
            ExecutionInDB record with queued status.
            
        Raises:
            IntegrationException: If validation fails or event publishing fails.
        """
        await self._ensure_initialized()

        # Track metrics
        ACTIVE_EXECUTIONS.inc()
        QUEUE_DEPTH.inc()

        lang_and_version = f"{lang}-{lang_version}"
        start_time = time()
        created_execution: ExecutionInDB | None = None

        try:
            # Validate runtime
            try:
                runtime_cfg = self._validate_runtime(lang, lang_version)
            except RuntimeNotSupportedError as e:
                raise IntegrationException(
                    status_code=400,
                    detail=str(e)
                ) from e

            # Extract user info
            user_id, session_id = self._extract_user_info(user, request)

            # Create execution record
            execution_create = ExecutionCreate(
                script=script,
                lang=lang,
                lang_version=lang_version,
                status=ExecutionStatus.QUEUED,
            )

            execution_data = execution_create.model_dump()
            if user_id:
                execution_data['user_id'] = user_id

            created_execution = await self.execution_repo.create_execution(
                ExecutionInDB(**execution_data)
            )

            logger.info(
                "Created execution record",
                extra={
                    "execution_id": str(created_execution.execution_id),
                    "lang": lang,
                    "lang_version": lang_version,
                    "user_id": user_id,
                    "script_length": len(script),
                }
            )

            # Extract request metadata
            client_ip, user_agent = self._extract_request_metadata(request)

            # Create event metadata
            metadata = self._create_event_metadata(
                user_id=user_id,
                session_id=session_id,
                client_ip=client_ip,
                user_agent=user_agent,
            )

            # Determine timeout
            timeout = timeout_override or self.settings.K8S_POD_EXECUTION_TIMEOUT

            # Create execution requested event
            event = ExecutionRequestedEvent(
                execution_id=created_execution.execution_id,
                script=script,
                language=lang,
                language_version=lang_version,
                runtime_image=runtime_cfg.image,
                runtime_command=runtime_cfg.command,
                runtime_filename=runtime_cfg.file_name,
                timeout_seconds=timeout,
                cpu_limit=self.settings.K8S_POD_CPU_LIMIT,
                memory_limit=self.settings.K8S_POD_MEMORY_LIMIT,
                cpu_request=self.settings.K8S_POD_CPU_REQUEST,
                memory_request=self.settings.K8S_POD_MEMORY_REQUEST,
                priority=priority,
                metadata=metadata,
            )

            # Store event in event store
            if self.event_store:
                stored = await self.event_store.store_event(event)
                if not stored:
                    logger.warning(
                        f"Failed to store event {event.event_id} in event store"
                    )

            # Publish event to Kafka
            if not self.producer:
                raise EventPublishError("Producer not available")
            
            try:
                # Get the correct Kafka topic for the event type
                topic = get_topic_for_event(EventType.EXECUTION_REQUESTED)
                await self.producer.send_event(
                    event=event,
                    topic=str(topic)  # Convert KafkaTopic enum to string
                )

                logger.info(
                    "Published execution request event",
                    extra={
                        "execution_id": str(created_execution.execution_id),
                        "event_id": str(event.event_id),
                        "correlation_id": str(metadata.correlation_id),
                    }
                )
            except Exception as e:
                raise EventPublishError(
                    "Failed to submit execution request to processing queue"
                ) from e

            # Track queue wait time
            queue_wait_duration = time() - start_time
            QUEUE_WAIT_TIME.labels(lang_and_version=lang_and_version).observe(queue_wait_duration)

            return created_execution

        except Exception as e:
            logger.error(
                "Failed to create execution",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "lang": lang,
                    "lang_version": lang_version,
                },
                exc_info=True
            )

            ERROR_COUNTER.labels(error_type=type(e).__name__).inc()

            # Update execution status if we created it
            if created_execution:
                await self._update_execution_error(
                    created_execution.execution_id,
                    f"Failed to submit execution: {str(e)}"
                )

            # Re-raise IntegrationException as-is
            if isinstance(e, IntegrationException):
                raise

            # Wrap other exceptions
            if isinstance(e, EventPublishError):
                raise IntegrationException(
                    status_code=503,
                    detail=str(e)
                ) from e

            raise IntegrationException(
                status_code=500,
                detail="Failed to submit execution request"
            ) from e

        finally:
            ACTIVE_EXECUTIONS.dec()
            QUEUE_DEPTH.dec()

    async def _update_execution_error(
            self,
            execution_id: str,
            error_message: str
    ) -> None:
        """
        Update execution status to error.
        
        Args:
            execution_id: Execution identifier.
            error_message: Error message to set.
        """
        try:
            await self.execution_repo.update_execution(
                execution_id,
                ExecutionUpdate(
                    status=ExecutionStatus.ERROR,
                    errors=error_message
                ).model_dump(exclude_unset=True)
            )
        except Exception as update_error:
            logger.error(
                f"Failed to update execution status: {update_error}",
                extra={"execution_id": execution_id}
            )

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        """
        Get execution result from database.
        
        In the event-driven architecture, results are updated asynchronously
        by worker services processing events. This method simply retrieves
        the current state from the database.
        
        Args:
            execution_id: UUID of the execution.
            
        Returns:
            Current execution state.
            
        Raises:
            IntegrationException: If execution not found.
        """
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            raise IntegrationException(
                status_code=404,
                detail=f"Execution {execution_id} not found"
            )

        logger.debug(
            "Retrieved execution result",
            extra={
                "execution_id": execution_id,
                "status": execution.status,
                "has_output": bool(execution.output),
                "has_errors": bool(execution.errors),
                "created_at": execution.created_at.isoformat() if execution.created_at else None,
                "updated_at": execution.updated_at.isoformat() if execution.updated_at else None,
            }
        )

        return execution

    async def get_execution_events(
            self,
            execution_id: str,
            event_types: EventFilter = None,
            limit: int = 100,
    ) -> list[BaseEvent]:
        """
        Get all events for an execution from the event store.
        
        Args:
            execution_id: UUID of the execution.
            event_types: Filter by specific event types.
            limit: Maximum number of events to return.
            
        Returns:
            List of events for the execution.
        """
        await self._ensure_initialized()

        if not self.event_store:
            logger.warning("Event store not available")
            return []

        # Use the correct method name - get_execution_events instead of get_events_by_execution
        events = await self.event_store.get_execution_events(
            execution_id=execution_id,
            event_types=event_types
        )

        # Apply limit if we got more events than requested
        if len(events) > limit:
            events = events[:limit]

        logger.debug(
            f"Retrieved {len(events)} events for execution {execution_id}",
            extra={
                "execution_id": execution_id,
                "event_count": len(events),
                "event_types": event_types,
            }
        )

        return events

    async def get_user_executions(
            self,
            user_id: UserId,
            status: ExecutionStatus | None = None,
            lang: str | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            limit: int = 50,
            skip: int = 0,
    ) -> list[ExecutionInDB]:
        """
        Get executions for a specific user with optional filters.
        
        Args:
            user_id: User identifier.
            status: Filter by execution status.
            lang: Filter by language.
            start_time: Filter by start time.
            end_time: Filter by end time.
            limit: Maximum number of results.
            skip: Number of results to skip.
            
        Returns:
            List of executions matching filters.
        """
        query = self._build_user_query(user_id, status, lang, start_time, end_time)

        executions = await self.execution_repo.get_executions(
            query=query,
            limit=limit,
            skip=skip,
            sort=[("created_at", -1)]
        )

        logger.debug(
            f"Retrieved {len(executions)} executions for user",
            extra={
                "user_id": str(user_id),
                "filters": {k: v for k, v in query.items() if k != "user_id"},
                "limit": limit,
                "skip": skip,
            }
        )

        return executions

    async def count_user_executions(
            self,
            user_id: UserId,
            status: ExecutionStatus | None = None,
            lang: str | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
    ) -> int:
        """
        Count executions for a specific user with optional filters.
        
        Args:
            user_id: User identifier.
            status: Filter by execution status.
            lang: Filter by language.
            start_time: Filter by start time.
            end_time: Filter by end time.
            
        Returns:
            Count of executions matching filters.
        """
        query = self._build_user_query(user_id, status, lang, start_time, end_time)
        return await self.execution_repo.count_executions(query)

    def _build_user_query(
            self,
            user_id: UserId,
            status: ExecutionStatus | None = None,
            lang: str | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
    ) -> ExecutionQuery:
        """
        Build MongoDB query for user executions.
        
        Args:
            user_id: User identifier.
            status: Filter by execution status.
            lang: Filter by language.
            start_time: Filter by start time.
            end_time: Filter by end time.
            
        Returns:
            MongoDB query dictionary.
        """
        query: ExecutionQuery = {"user_id": str(user_id)}

        if status:
            query["status"] = status

        if lang:
            query["lang"] = lang

        if start_time or end_time:
            time_filter = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query["created_at"] = time_filter

        return query

    async def delete_execution(self, execution_id: str) -> bool:
        """
        Delete an execution and publish deletion event.
        
        Args:
            execution_id: UUID of execution to delete.
            
        Returns:
            True if deletion successful.
        """
        # Delete from database
        deleted = await self.execution_repo.delete_execution(execution_id)

        if not deleted:
            logger.warning(f"Execution {execution_id} not found for deletion")
            return False

        logger.info(
            "Deleted execution",
            extra={"execution_id": execution_id}
        )

        # Publish deletion event
        await self._publish_deletion_event(execution_id)

        return True

    async def _publish_deletion_event(self, execution_id: str) -> None:
        """
        Publish execution deletion/cancellation event.
        
        Args:
            execution_id: UUID of deleted execution.
        """
        await self._ensure_initialized()

        if not self.producer:
            logger.warning("Producer not available for deletion event")
            return

        try:
            metadata = self._create_event_metadata()

            # Create proper cancellation event instead of raw dict
            event = ExecutionCancelledEvent(
                execution_id=execution_id,
                reason="user_requested",
                cancelled_by=metadata.user_id,
                metadata=metadata
            )

            # Store in event store
            if self.event_store:
                with suppress(Exception):
                    await self.event_store.store_event(event)

            # Get the correct Kafka topic and publish event
            topic = get_topic_for_event(EventType.EXECUTION_CANCELLED)
            await self.producer.send_event(
                topic=str(topic),  # Convert KafkaTopic enum to string
                event=event,
                key=execution_id
            )

            logger.info(
                "Published cancellation event",
                extra={
                    "execution_id": execution_id,
                    "event_id": str(event.event_id),
                }
            )

        except Exception as e:
            # Log but don't fail the deletion
            logger.error(
                "Failed to publish deletion event",
                extra={
                    "execution_id": execution_id,
                    "error": str(e)
                },
                exc_info=True
            )

    async def get_execution_stats(
            self,
            user_id: UserId | None = None,
            time_range: TimeRange = (None, None)
    ) -> ExecutionStats:
        """
        Get execution statistics.
        
        Args:
            user_id: Optional user filter.
            time_range: Tuple of (start_time, end_time).
            
        Returns:
            Dictionary containing execution statistics.
        """
        query = self._build_stats_query(user_id, time_range)

        # Get executions for stats
        executions = await self.execution_repo.get_executions(
            query=query,
            limit=1000  # Reasonable limit for stats
        )

        return self._calculate_stats(executions)

    def _build_stats_query(
            self,
            user_id: UserId | None,
            time_range: TimeRange
    ) -> ExecutionQuery:
        """
        Build query for statistics.
        
        Args:
            user_id: Optional user filter.
            time_range: Tuple of (start_time, end_time).
            
        Returns:
            MongoDB query dictionary.
        """
        query: ExecutionQuery = {}

        if user_id:
            query["user_id"] = str(user_id)

        start_time, end_time = time_range
        if start_time or end_time:
            time_filter = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query["created_at"] = time_filter

        return query

    def _calculate_stats(self, executions: list[ExecutionInDB]) -> ExecutionStats:
        """
        Calculate statistics from executions.
        
        Args:
            executions: List of executions to analyze.
            
        Returns:
            Statistics dictionary.
        """
        stats: ExecutionStats = {
            "total": len(executions),
            "by_status": {},
            "by_language": {},
            "average_duration_ms": 0,
            "success_rate": 0,
        }

        total_duration = 0.0
        successful = 0

        for execution in executions:
            # Count by status
            status = execution.status
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            # Count by language
            lang_key = f"{execution.lang}-{execution.lang_version}"
            stats["by_language"][lang_key] = stats["by_language"].get(lang_key, 0) + 1

            # Track success and duration
            if status == ExecutionStatus.COMPLETED:
                successful += 1
                if execution.created_at and execution.updated_at:
                    duration = (execution.updated_at - execution.created_at).total_seconds() * 1000
                    total_duration += duration

        # Calculate averages
        if stats["total"] > 0:
            stats["success_rate"] = successful / stats["total"]
            if successful > 0:
                stats["average_duration_ms"] = total_duration / successful

        return stats


# Dependency injection functions
async def get_execution_service(
        request: Request,
        execution_repo: ExecutionRepository = Depends(get_execution_repository),
) -> ExecutionService:
    """
    FastAPI dependency for getting execution service instance.
    
    This ensures proper initialization of the service with all required dependencies.
    """
    producer = await get_producer()
    event_store = get_event_store()
    settings = get_settings()

    return ExecutionService(
        execution_repo=execution_repo,
        producer=producer,
        event_store=event_store,
        settings=settings,
    )
