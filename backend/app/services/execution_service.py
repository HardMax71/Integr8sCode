import logging
from contextlib import contextmanager
from datetime import datetime
from time import time
from typing import Any, Generator, TypeAlias

from app.core.correlation import CorrelationContext
from app.core.metrics import ExecutionMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus, QueuePriority
from app.domain.events.typed import (
    DomainEvent,
    EventMetadata,
    ExecutionCancelledEvent,
    ExecutionRequestedEvent,
)
from app.domain.exceptions import InfrastructureError
from app.domain.execution import (
    DomainExecution,
    DomainExecutionCreate,
    ExecutionNotFoundError,
    ExecutionResultDomain,
    ResourceLimitsDomain,
)
from app.events.core import UnifiedProducer
from app.events.event_store import EventStore
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
        logger: logging.Logger,
        execution_metrics: ExecutionMetrics,
    ) -> None:
        """
        Initialize execution service.

        Args:
            execution_repo: Repository for execution data persistence.
            producer: Kafka producer for publishing events.
            event_store: Event store for event persistence.
            settings: Application settings.
            logger: Logger instance.
            execution_metrics: Metrics for tracking execution operations.
        """
        self.execution_repo = execution_repo
        self.producer = producer
        self.event_store = event_store
        self.settings = settings
        self.logger = logger
        self.metrics = execution_metrics

    @contextmanager
    def _track_active_execution(self) -> Generator[None, None, None]:  # noqa: D401
        """Increment active executions on enter and decrement on exit."""
        self.metrics.increment_active_executions()
        try:
            yield
        finally:
            self.metrics.decrement_active_executions()

    async def get_k8s_resource_limits(self) -> ResourceLimitsDomain:
        return ResourceLimitsDomain(
            cpu_limit=self.settings.K8S_POD_CPU_LIMIT,
            memory_limit=self.settings.K8S_POD_MEMORY_LIMIT,
            cpu_request=self.settings.K8S_POD_CPU_REQUEST,
            memory_request=self.settings.K8S_POD_MEMORY_REQUEST,
            execution_timeout=self.settings.K8S_POD_EXECUTION_TIMEOUT,
            supported_runtimes=self.settings.SUPPORTED_RUNTIMES,
        )

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
        priority: QueuePriority = QueuePriority.NORMAL,
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
            InfrastructureError: If validation fails or event publishing fails.
        """
        lang_and_version = f"{lang}-{lang_version}"
        start_time = time()

        # Log incoming request
        self.logger.info(
            "Received script execution request",
            extra={
                "lang": lang,
                "lang_version": lang_version,
                "script_length": len(script),
                "priority": priority,
                "timeout_override": timeout_override,
            },
        )

        runtime_cfg = RUNTIME_REGISTRY[lang][lang_version]

        with self._track_active_execution():
            # Create execution record
            created_execution = await self.execution_repo.create_execution(
                DomainExecutionCreate(
                    script=script,
                    lang=lang,
                    lang_version=lang_version,
                    user_id=user_id,
                )
            )

            self.logger.info(
                "Created execution record",
                extra={
                    "execution_id": str(created_execution.execution_id),
                    "lang": lang,
                    "lang_version": lang_version,
                    "user_id": user_id,
                    "script_length": len(script),
                },
            )

            # Metadata and event
            metadata = self._create_event_metadata(user_id=user_id, client_ip=client_ip, user_agent=user_agent)
            timeout = timeout_override or self.settings.K8S_POD_EXECUTION_TIMEOUT
            event = ExecutionRequestedEvent(
                execution_id=created_execution.execution_id,
                aggregate_id=created_execution.execution_id,
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

            # Publish to Kafka; on failure, mark error and raise
            try:
                await self.producer.produce(event_to_produce=event)
            except Exception as e:  # pragma: no cover - mapped behavior
                self.metrics.record_script_execution(ExecutionStatus.ERROR, lang_and_version)
                self.metrics.record_error(type(e).__name__)
                await self._update_execution_error(
                    created_execution.execution_id,
                    f"Failed to submit execution: {str(e)}",
                )
                raise InfrastructureError("Failed to submit execution request") from e

            # Success metrics and return
            duration = time() - start_time
            self.metrics.record_script_execution(ExecutionStatus.QUEUED, lang_and_version)
            self.metrics.record_queue_wait_time(duration, lang_and_version)
            self.logger.info(
                "Script execution submitted successfully",
                extra={
                    "execution_id": str(created_execution.execution_id),
                    "status": created_execution.status,
                    "duration_seconds": duration,
                },
            )
            return created_execution

    async def _update_execution_error(self, execution_id: str, error_message: str) -> None:
        result = ExecutionResultDomain(
            execution_id=execution_id,
            status=ExecutionStatus.ERROR,
            exit_code=-1,
            stdout="",
            stderr=error_message,
            resource_usage=None,
            metadata=None,
        )
        await self.execution_repo.write_terminal_result(result)

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
            ExecutionNotFoundError: If execution not found.
        """
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            self.logger.warning("Execution not found", extra={"execution_id": execution_id})
            raise ExecutionNotFoundError(execution_id)

        self.logger.info(
            "Execution result retrieved successfully",
            extra={
                "execution_id": execution_id,
                "status": execution.status,
                "lang": execution.lang,
                "lang_version": execution.lang_version,
                "has_output": bool(execution.stdout),
                "has_errors": bool(execution.stderr),
                "resource_usage": execution.resource_usage,
            },
        )

        return execution

    async def get_execution_events(
        self,
        execution_id: str,
        event_types: EventFilter = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
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
        events = await self.event_store.get_execution_events(execution_id=execution_id, event_types=event_types)

        # Apply limit if we got more events than requested
        if len(events) > limit:
            events = events[:limit]

        self.logger.debug(
            f"Retrieved {len(events)} events for execution {execution_id}",
            extra={
                "execution_id": execution_id,
                "event_count": len(events),
                "event_types": event_types,
            },
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
            query=query, limit=limit, skip=skip, sort=[("created_at", -1)]
        )

        self.logger.debug(
            f"Retrieved {len(executions)} executions for user",
            extra={
                "user_id": str(user_id),
                "filters": {k: v for k, v in query.items() if k != "user_id"},
                "limit": limit,
                "skip": skip,
            },
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
            self.logger.warning("Execution not found for deletion", extra={"execution_id": execution_id})
            raise ExecutionNotFoundError(execution_id)

        self.logger.info("Deleted execution", extra={"execution_id": execution_id})

        await self._publish_deletion_event(execution_id)

        return True

    async def _publish_deletion_event(self, execution_id: str) -> None:
        """
        Publish execution deletion/cancellation event.

        Args:
            execution_id: UUID of deleted execution.
        """
        metadata = self._create_event_metadata()

        event = ExecutionCancelledEvent(
            execution_id=execution_id, reason="user_requested", cancelled_by=metadata.user_id, metadata=metadata
        )

        await self.producer.produce(event_to_produce=event, key=execution_id)

        self.logger.info(
            "Published cancellation event",
            extra={
                "execution_id": execution_id,
                "event_id": str(event.event_id),
            },
        )

    async def get_execution_stats(
        self, user_id: UserId | None = None, time_range: TimeRange = (None, None)
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
            limit=1000,  # Reasonable limit for stats
        )

        return self._calculate_stats(executions)

    def _build_stats_query(self, user_id: UserId | None, time_range: TimeRange) -> ExecutionQuery:
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
