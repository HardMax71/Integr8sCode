from contextlib import suppress
from datetime import datetime
from time import time
from typing import Any, TypeAlias

from app.core.correlation import CorrelationContext
from app.core.exceptions import IntegrationException, ServiceError
from app.core.logging import logger
from app.core.metrics.context import get_execution_metrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.execution.models import DomainExecution
from app.events.core.producer import UnifiedProducer
from app.events.event_store import EventStore
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionCancelledEvent,
    ExecutionRequestedEvent,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.runtime_registry import RUNTIME_REGISTRY
from app.settings import Settings

# Type aliases for better readability
UserId: TypeAlias = str
EventFilter: TypeAlias = list[EventType] | None
TimeRange: TypeAlias = tuple[datetime | None, datetime | None]
ExecutionQuery: TypeAlias = dict[str, Any]
ExecutionStats: TypeAlias = dict[str, Any]


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
            producer: UnifiedProducer,
            event_store: EventStore,
            settings: Settings,
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
        self.settings = settings
        self.metrics = get_execution_metrics()

    async def get_k8s_resource_limits(self) -> dict[str, Any]:
        return {
            "cpu_limit": self.settings.K8S_POD_CPU_LIMIT,
            "memory_limit": self.settings.K8S_POD_MEMORY_LIMIT,
            "cpu_request": self.settings.K8S_POD_CPU_REQUEST,
            "memory_request": self.settings.K8S_POD_MEMORY_REQUEST,
            "execution_timeout": self.settings.K8S_POD_EXECUTION_TIMEOUT,
            "supported_runtimes": self.settings.SUPPORTED_RUNTIMES,
        }

    async def get_example_scripts(self) -> dict[str, str]:
        return self.settings.EXAMPLE_SCRIPTS

    def _create_event_metadata(
            self,
            user_id: str | None = None,
            client_ip: str | None = None,
            user_agent: str | None = None,
    ) -> EventMetadata:
        """
        Create standardized event metadata.
        
        Args:
            user_id: User identifier.
            client_ip: Client IP address.
            user_agent: User agent string.
            
        Returns:
            EventMetadata instance.
        """
        correlation_id = CorrelationContext.get_correlation_id()

        return EventMetadata(
            correlation_id=correlation_id,
            service_name="execution-service",
            service_version="2.0.0",
            user_id=user_id,
            ip_address=client_ip,
            user_agent=user_agent,
        )

    async def execute_script(
            self,
            script: str,
            user_id: str,
            *,
            client_ip: str | None,
            user_agent: str | None,
            lang: str = "python",
            lang_version: str = "3.11",
            priority: int = 5,
            timeout_override: int | None = None,
    ) -> DomainExecution:
        """
        Execute a script by creating an execution record and publishing an event.
        
        Args:
            script: The code to execute.
            lang: Programming language.
            lang_version: Language version.
            user_id: ID of the user requesting execution.
            priority: Execution priority (1-10, lower is higher priority).
            timeout_override: Override default timeout in seconds.
            
        Returns:
            DomainExecution record with queued status.
            
        Raises:
            IntegrationException: If validation fails or event publishing fails.
        """
        lang_and_version = f"{lang}-{lang_version}"
        start_time = time()

        # Log incoming request
        logger.info(
            "Received script execution request",
            extra={
                "lang": lang,
                "lang_version": lang_version,
                "script_length": len(script),
                "priority": priority,
                "timeout_override": timeout_override,
            }
        )

        # Track metrics
        self.metrics.increment_active_executions()
        created_execution: DomainExecution | None = None

        # Runtime selection relies on API schema validation
        runtime_cfg = RUNTIME_REGISTRY[lang][lang_version]

        try:
            # Create execution record
            created_execution = await self.execution_repo.create_execution(
                DomainExecution(
                    script=script,
                    lang=lang,
                    lang_version=lang_version,
                    status=ExecutionStatus.QUEUED,
                    user_id=user_id,
                )
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

            # Metadata and event
            metadata = self._create_event_metadata(user_id=user_id, client_ip=client_ip, user_agent=user_agent)
            timeout = timeout_override or self.settings.K8S_POD_EXECUTION_TIMEOUT
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

            with suppress(Exception):
                await self.event_store.store_event(event)

            # Publish to Kafka; on failure, mark error and raise
            try:
                await self.producer.produce(event_to_produce=event)
            except Exception as e:
                self.metrics.record_script_execution(ExecutionStatus.ERROR, lang_and_version)
                self.metrics.record_error(type(e).__name__)
                if created_execution:
                    await self._update_execution_error(created_execution.execution_id,
                                                       f"Failed to submit execution: {str(e)}")
                raise IntegrationException(status_code=500, detail="Failed to submit execution request") from e

            # Success metrics and return
            duration = time() - start_time
            self.metrics.record_script_execution(ExecutionStatus.QUEUED, lang_and_version)
            self.metrics.record_queue_wait_time(duration, lang_and_version)
            logger.info(
                "Script execution submitted successfully",
                extra={
                    "execution_id": str(created_execution.execution_id),
                    "status": created_execution.status,
                    "duration_seconds": duration,
                }
            )
            return created_execution
        finally:
            self.metrics.decrement_active_executions()

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
                {
                    "status": ExecutionStatus.ERROR,
                    "errors": error_message,
                }
            )
        except Exception as update_error:
            logger.error(
                f"Failed to update execution status: {update_error}",
                extra={"execution_id": execution_id}
            )

    async def get_execution_result(self, execution_id: str) -> DomainExecution:
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
            logger.warning(
                "Execution not found",
                extra={"execution_id": execution_id}
            )
            raise IntegrationException(
                status_code=404,
                detail=f"Execution {execution_id} not found"
            )

        logger.info(
            "Execution result retrieved successfully",
            extra={
                "execution_id": execution_id,
                "status": execution.status,
                "lang": execution.lang,
                "lang_version": execution.lang_version,
                "has_output": bool(execution.output),
                "has_errors": bool(execution.errors),
                "resource_usage": execution.resource_usage,
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
    ) -> list[DomainExecution]:
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
            query["status"] = status.value

        if lang:
            query["lang"] = lang

        if start_time or end_time:
            time_filter = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query["updated_at"] = time_filter

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
            raise ServiceError("Execution not found", status_code=404)

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
            with suppress(Exception):
                await self.event_store.store_event(event)

            await self.producer.produce(
                event_to_produce=event,
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

    def _calculate_stats(self, executions: list[DomainExecution]) -> ExecutionStats:
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
