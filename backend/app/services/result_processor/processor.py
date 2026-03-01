import structlog

from app.core.metrics import ExecutionMetrics
from app.db import ExecutionRepository
from app.domain.enums import ExecutionErrorType, ExecutionStatus, StorageType
from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    ResultFailedEvent,
    ResultStoredEvent,
)
from app.domain.execution import ExecutionNotFoundError, ExecutionResultDomain
from app.events import UnifiedProducer
from app.settings import Settings


class ResultProcessor:
    """Service for processing execution completion events and storing results."""

    def __init__(
            self,
            execution_repo: ExecutionRepository,
            producer: UnifiedProducer,
            settings: Settings,
            logger: structlog.stdlib.BoundLogger,
            execution_metrics: ExecutionMetrics,
    ) -> None:
        self._execution_repo = execution_repo
        self._producer = producer
        self._settings = settings
        self._metrics = execution_metrics
        self.logger = logger

    async def handle_execution_completed(self, event: DomainEvent) -> None:
        """Handle execution completed event."""
        if not isinstance(event, ExecutionCompletedEvent):
            raise TypeError(f"Expected ExecutionCompletedEvent, got {type(event).__name__}")

        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            raise ExecutionNotFoundError(event.execution_id)

        lang_and_version = f"{exec_obj.lang}-{exec_obj.lang_version}"

        self._metrics.record_script_execution(ExecutionStatus.COMPLETED, lang_and_version)

        if event.resource_usage is None:
            raise ValueError(f"ExecutionCompletedEvent {event.execution_id} missing resource_usage")

        runtime_seconds = event.resource_usage.execution_time_wall_seconds
        self._metrics.record_execution_duration(runtime_seconds, lang_and_version)

        memory_mib = event.resource_usage.peak_memory_kb / 1024
        self._metrics.record_memory_usage(memory_mib, lang_and_version)

        settings_limit = self._settings.K8S_POD_MEMORY_LIMIT
        memory_limit_mib = int(settings_limit.rstrip("Mi"))  # TODO: Less brittle acquisition of limit
        memory_percent = (memory_mib / memory_limit_mib) * 100
        self._metrics.memory_utilization_percent.record(
            memory_percent, attributes={"lang_and_version": lang_and_version}
        )

        result = ExecutionResultDomain(
            execution_id=event.execution_id,
            exit_code=event.exit_code,
            stdout=event.stdout,
            stderr=event.stderr,
            resource_usage=event.resource_usage,
            metadata=event.metadata,
            status=ExecutionStatus.COMPLETED,
        )

        meta = event.metadata
        try:
            await self._execution_repo.write_terminal_result(result)
            await self._publish_result_stored(result, meta.user_id)
        except Exception as e:
            self.logger.error(f"Failed to handle ExecutionCompletedEvent: {e}", exc_info=True)
            await self._publish_result_failed(event.execution_id, str(e), meta.user_id)

    async def handle_execution_failed(self, event: DomainEvent) -> None:
        """Handle execution failed event."""
        if not isinstance(event, ExecutionFailedEvent):
            raise TypeError(f"Expected ExecutionFailedEvent, got {type(event).__name__}")

        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            raise ExecutionNotFoundError(event.execution_id)

        if event.error_type is not None:
            self._metrics.record_error(event.error_type)
        lang_and_version = f"{exec_obj.lang}-{exec_obj.lang_version}"

        self._metrics.record_script_execution(ExecutionStatus.FAILED, lang_and_version)
        result = ExecutionResultDomain(
            execution_id=event.execution_id,
            exit_code=event.exit_code,
            stdout=event.stdout,
            stderr=event.stderr,
            resource_usage=event.resource_usage,
            error_type=event.error_type,
            metadata=event.metadata,
            status=ExecutionStatus.FAILED,
        )
        meta = event.metadata
        try:
            await self._execution_repo.write_terminal_result(result)
            await self._publish_result_stored(result, meta.user_id)
        except Exception as e:
            self.logger.error(f"Failed to handle ExecutionFailedEvent: {e}", exc_info=True)
            await self._publish_result_failed(event.execution_id, str(e), meta.user_id)

    async def handle_execution_timeout(self, event: DomainEvent) -> None:
        """Handle execution timeout event."""
        if not isinstance(event, ExecutionTimeoutEvent):
            raise TypeError(f"Expected ExecutionTimeoutEvent, got {type(event).__name__}")

        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            raise ExecutionNotFoundError(event.execution_id)

        self._metrics.record_error(ExecutionErrorType.TIMEOUT)
        lang_and_version = f"{exec_obj.lang}-{exec_obj.lang_version}"

        self._metrics.record_script_execution(ExecutionStatus.TIMEOUT, lang_and_version)
        self._metrics.record_execution_duration(event.timeout_seconds, lang_and_version)

        result = ExecutionResultDomain(
            execution_id=event.execution_id,
            exit_code=-1,
            stdout=event.stdout,
            stderr=event.stderr,
            resource_usage=event.resource_usage,
            error_type=ExecutionErrorType.TIMEOUT,
            metadata=event.metadata,
            status=ExecutionStatus.TIMEOUT,
        )
        meta = event.metadata
        try:
            await self._execution_repo.write_terminal_result(result)
            await self._publish_result_stored(result, meta.user_id)
        except Exception as e:
            self.logger.error(f"Failed to handle ExecutionTimeoutEvent: {e}", exc_info=True)
            await self._publish_result_failed(event.execution_id, str(e), meta.user_id)

    async def _publish_result_stored(self, result: ExecutionResultDomain, user_id: str) -> None:
        """Publish result stored event."""
        size_bytes = len(result.stdout) + len(result.stderr)
        event = ResultStoredEvent(
            execution_id=result.execution_id,
            storage_path=result.execution_id,
            size_bytes=size_bytes,
            storage_type=StorageType.DATABASE,
            metadata=EventMetadata(
                service_name="result-processor",
                service_version="1.0.0",
                user_id=user_id,
            ),
        )
        await self._producer.produce(event_to_produce=event, key=result.execution_id)

    async def _publish_result_failed(
        self, execution_id: str, error_message: str, user_id: str,
    ) -> None:
        """Publish result processing failed event."""
        event = ResultFailedEvent(
            execution_id=execution_id,
            metadata=EventMetadata(
                service_name="result-processor",
                service_version="1.0.0",
                user_id=user_id,
            ),
        )
        await self._producer.produce(event_to_produce=event, key=execution_id)
