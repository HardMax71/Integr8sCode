import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from time import time
from typing import Any, Generator
from uuid import uuid4

from app.core.correlation import CorrelationContext
from app.core.metrics import ExecutionMetrics
from app.db.repositories import ExecutionRepository
from app.domain.enums import CancelStatus, EventType, ExecutionStatus, QueuePriority
from app.domain.events import (
    BaseEvent,
    EventMetadata,
    ExecutionCancelledEvent,
    ExecutionRequestedEvent,
)
from app.domain.exceptions import InfrastructureError
from app.domain.execution import (
    CancelResult,
    DomainExecution,
    DomainExecutionCreate,
    ExecutionNotFoundError,
    ExecutionResultDomain,
    ExecutionTerminalError,
    ResourceLimitsDomain,
)
from app.domain.idempotency import KeyStrategy
from app.events.core import UnifiedProducer
from app.runtime_registry import RUNTIME_REGISTRY
from app.services.idempotency import IdempotencyManager
from app.settings import Settings


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
        settings: Settings,
        logger: logging.Logger,
        execution_metrics: ExecutionMetrics,
        idempotency_manager: IdempotencyManager,
    ) -> None:
        """
        Initialize execution service.

        Args:
            execution_repo: Repository for execution data persistence.
            producer: Kafka producer for publishing events.
            settings: Application settings.
            logger: Logger instance.
            execution_metrics: Metrics for tracking execution operations.
            idempotency_manager: Manager for HTTP idempotency.
        """
        self.execution_repo = execution_repo
        self.producer = producer
        self.settings = settings
        self.logger = logger
        self.metrics = execution_metrics
        self.idempotency_manager = idempotency_manager

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
                    "execution_id": created_execution.execution_id,
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
                await self.producer.produce(event_to_produce=event, key=created_execution.execution_id)
            except Exception as e:  # pragma: no cover - mapped behavior
                self.metrics.record_script_execution(ExecutionStatus.ERROR, lang_and_version)
                self.metrics.record_error(type(e).__name__)
                await self._update_execution_error(
                    created_execution.execution_id,
                    f"Failed to submit execution: {e}",
                )
                raise InfrastructureError("Failed to submit execution request") from e

            # Success metrics and return
            duration = time() - start_time
            self.metrics.record_script_execution(ExecutionStatus.QUEUED, lang_and_version)
            self.metrics.record_queue_wait_time(duration, lang_and_version)
            self.logger.info(
                "Script execution submitted successfully",
                extra={
                    "execution_id": created_execution.execution_id,
                    "status": created_execution.status,
                    "duration_seconds": duration,
                },
            )
            return created_execution

    async def cancel_execution(
        self,
        execution_id: str,
        current_status: ExecutionStatus,
        user_id: str,
        reason: str = "User requested cancellation",
    ) -> CancelResult:
        """
        Cancel a running or queued execution.

        Args:
            execution_id: UUID of the execution.
            current_status: Current status of the execution.
            user_id: User requesting cancellation.
            reason: Cancellation reason.

        Returns:
            CancelResult with status and event info.

        Raises:
            ExecutionTerminalError: If execution is in a terminal state.
        """
        terminal_states = {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT}

        if current_status in terminal_states:
            raise ExecutionTerminalError(execution_id, current_status)

        if current_status == ExecutionStatus.CANCELLED:
            return CancelResult(
                execution_id=execution_id,
                status=CancelStatus.ALREADY_CANCELLED,
                message="Execution was already cancelled",
                event_id=None,
            )

        metadata = self._create_event_metadata(user_id=user_id)
        event = ExecutionCancelledEvent(
            execution_id=execution_id,
            reason=reason,
            cancelled_by=user_id,
            metadata=metadata,
        )

        await self.producer.produce(event_to_produce=event, key=execution_id)

        self.logger.info(
            "Published cancellation event",
            extra={"execution_id": execution_id, "event_id": event.event_id},
        )

        return CancelResult(
            execution_id=execution_id,
            status=CancelStatus.CANCELLATION_REQUESTED,
            message="Cancellation request submitted",
            event_id=event.event_id,
        )

    async def execute_script_idempotent(
        self,
        script: str,
        user_id: str,
        *,
        client_ip: str | None,
        user_agent: str | None,
        lang: str = "python",
        lang_version: str = "3.11",
        idempotency_key: str | None = None,
    ) -> DomainExecution:
        """
        Execute a script with optional idempotency support.

        Args:
            script: The code to execute.
            user_id: ID of the user requesting execution.
            client_ip: Client IP address.
            user_agent: User agent string.
            lang: Programming language.
            lang_version: Language version.
            idempotency_key: Optional HTTP idempotency key.

        Returns:
            DomainExecution record.
        """
        if not idempotency_key:
            return await self.execute_script(
                script=script,
                lang=lang,
                lang_version=lang_version,
                user_id=user_id,
                client_ip=client_ip,
                user_agent=user_agent,
            )

        pseudo_event = BaseEvent(
            event_id=str(uuid4()),
            event_type=EventType.EXECUTION_REQUESTED,
            timestamp=datetime.now(timezone.utc),
            metadata=EventMetadata(
                user_id=user_id,
                correlation_id=str(uuid4()),
                service_name="api",
                service_version="1.0.0",
            ),
        )
        custom_key = f"http:{user_id}:{idempotency_key}"

        idempotency_result = await self.idempotency_manager.check_and_reserve(
            event=pseudo_event,
            key_strategy=KeyStrategy.CUSTOM,
            custom_key=custom_key,
            ttl_seconds=86400,
        )

        if idempotency_result.is_duplicate:
            cached_json = await self.idempotency_manager.get_cached_json(
                event=pseudo_event,
                key_strategy=KeyStrategy.CUSTOM,
                custom_key=custom_key,
            )
            return DomainExecution.model_validate_json(cached_json)

        try:
            exec_result = await self.execute_script(
                script=script,
                lang=lang,
                lang_version=lang_version,
                user_id=user_id,
                client_ip=client_ip,
                user_agent=user_agent,
            )

            await self.idempotency_manager.mark_completed_with_json(
                event=pseudo_event,
                cached_json=exec_result.model_dump_json(),
                key_strategy=KeyStrategy.CUSTOM,
                custom_key=custom_key,
            )

            return exec_result

        except Exception as e:
            await self.idempotency_manager.mark_failed(
                event=pseudo_event,
                error=str(e),
                key_strategy=KeyStrategy.CUSTOM,
                custom_key=custom_key,
            )
            raise

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

    async def get_user_executions(
        self,
        user_id: str,
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
                "user_id": user_id,
                "filters": {k: v for k, v in query.items() if k != "user_id"},
                "limit": limit,
                "skip": skip,
            },
        )

        return executions

    async def count_user_executions(
        self,
        user_id: str,
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
        user_id: str,
        status: ExecutionStatus | None = None,
        lang: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
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
        query: dict[str, Any] = {"user_id": user_id}

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
                "event_id": event.event_id,
            },
        )

    async def get_execution_stats(
        self, user_id: str | None = None, time_range: tuple[datetime | None, datetime | None] = (None, None)
    ) -> dict[str, Any]:
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

    def _build_stats_query(
        self, user_id: str | None, time_range: tuple[datetime | None, datetime | None]
    ) -> dict[str, Any]:
        """
        Build query for statistics.

        Args:
            user_id: Optional user filter.
            time_range: Tuple of (start_time, end_time).

        Returns:
            MongoDB query dictionary.
        """
        query: dict[str, Any] = {}

        if user_id:
            query["user_id"] = user_id

        start_time, end_time = time_range
        if start_time or end_time:
            time_filter = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query["created_at"] = time_filter

        return query

    def _calculate_stats(self, executions: list[DomainExecution]) -> dict[str, Any]:
        """
        Calculate statistics from executions.

        Args:
            executions: List of executions to analyze.

        Returns:
            Statistics dictionary.
        """
        stats: dict[str, Any] = {
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
