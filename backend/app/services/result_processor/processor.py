import structlog
from opentelemetry import trace
from opentelemetry.util.types import AttributeValue
from pymongo.errors import PyMongoError

from app.db import ExecutionRepository
from app.domain.enums import ExecutionErrorType, ExecutionStatus, StorageType
from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
    PodScheduledEvent,
    ResultFailedEvent,
    ResultStoredEvent,
)
from app.domain.execution import ExecutionResultDomain
from app.events import UnifiedProducer
from app.infrastructure.kafka.topics import POD_EVENT_STATUS
from app.runtime_registry import parse_quantity
from app.services.runtime_settings import RuntimeSettingsLoader


class ResultProcessor:
    """Stores an execution's status and final result, then publishes what happened."""

    def __init__(
        self,
        execution_repo: ExecutionRepository,
        producer: UnifiedProducer,
        runtime_settings: RuntimeSettingsLoader,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
    ) -> None:
        self._execution_repo = execution_repo
        self._producer = producer
        self._runtime_settings = runtime_settings
        self._tracer = tracer
        self.logger = logger

    async def handle_pod_progress(self, event: PodScheduledEvent | PodRunningEvent) -> None:
        """Move the stored execution status forward when its pod is scheduled or starts running."""
        status = POD_EVENT_STATUS[event.event_type]
        if await self._execution_repo.advance_status(event.execution_id, status):
            self.logger.info("Execution status advanced", execution_id=event.execution_id, status=status)

    async def handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Store a completed execution's result, then publish the event and result_stored."""
        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            self.logger.warning("Execution deleted before its result was stored", execution_id=event.execution_id)
            return

        memory_mib = event.resource_usage.peak_memory_kb / 1024
        limits = await self._runtime_settings.get_language_limits(exec_obj.lang)
        memory_limit_mib = float(parse_quantity(limits.memory_limit)) / 2**20
        attributes: dict[str, AttributeValue] = {
            "execution.status": ExecutionStatus.COMPLETED,
            "execution.lang_and_version": f"{exec_obj.lang}-{exec_obj.lang_version}",
            "execution.runtime_seconds": event.resource_usage.execution_time_wall_seconds,
            "execution.memory_mib": memory_mib,
            "execution.memory_percent": memory_mib / memory_limit_mib * 100,
        }
        with self._tracer.start_as_current_span("execution.result", attributes=attributes):
            result = ExecutionResultDomain(
                execution_id=event.execution_id,
                exit_code=event.exit_code,
                stdout=event.stdout,
                stderr=event.stderr,
                resource_usage=event.resource_usage,
                status=ExecutionStatus.COMPLETED,
            )
            await self._store(result, event.metadata, event.aggregate_id, announce=(event,))

    async def handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Store a failed execution's result, then publish the event and result_stored."""
        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            self.logger.warning("Execution deleted before its result was stored", execution_id=event.execution_id)
            return

        attributes = {
            "execution.status": ExecutionStatus.FAILED,
            "execution.lang_and_version": f"{exec_obj.lang}-{exec_obj.lang_version}",
        }
        if event.error_type is not None:
            attributes["execution.error_type"] = event.error_type
        with self._tracer.start_as_current_span("execution.result", attributes=attributes):
            result = ExecutionResultDomain(
                execution_id=event.execution_id,
                exit_code=event.exit_code,
                stdout=event.stdout,
                stderr=event.stderr,
                resource_usage=event.resource_usage,
                error_type=event.error_type,
                status=ExecutionStatus.FAILED,
            )
            await self._store(result, event.metadata, event.aggregate_id, announce=(event,))

    async def handle_lost_request(self, execution_id: str) -> None:
        """Fail an execution whose queued request expired before a slot freed up, so it doesn't stay queued."""
        exec_obj = await self._execution_repo.get_execution(execution_id)
        if exec_obj is None:
            self.logger.warning("Execution deleted before its lost request was failed", execution_id=execution_id)
            return
        await self.handle_execution_failed(
            ExecutionFailedEvent(
                execution_id=execution_id,
                aggregate_id=execution_id,
                error_type=ExecutionErrorType.SYSTEM_ERROR,
                exit_code=-1,
                stderr="The execution waited in the queue until its request expired. Run it again.",
                metadata=EventMetadata(
                    service_name="execution-scheduler", service_version="1.0.0", user_id=exec_obj.user_id or ""
                ),
            )
        )

    async def handle_execution_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Store a timed-out execution's result, then publish the event and result_stored."""
        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            self.logger.warning("Execution deleted before its result was stored", execution_id=event.execution_id)
            return

        attributes: dict[str, AttributeValue] = {
            "execution.status": ExecutionStatus.TIMEOUT,
            "execution.lang_and_version": f"{exec_obj.lang}-{exec_obj.lang_version}",
            "execution.error_type": ExecutionErrorType.TIMEOUT,
            "execution.runtime_seconds": event.timeout_seconds,
        }
        with self._tracer.start_as_current_span("execution.result", attributes=attributes):
            result = ExecutionResultDomain(
                execution_id=event.execution_id,
                exit_code=-1,
                stdout=event.stdout,
                stderr=event.stderr,
                resource_usage=event.resource_usage,
                error_type=ExecutionErrorType.TIMEOUT,
                status=ExecutionStatus.TIMEOUT,
            )
            await self._store(result, event.metadata, event.aggregate_id, announce=(event,))

    async def handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Store the cancelled status of an execution that hasn't finished, then publish result_stored."""
        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            self.logger.info("Cancelled execution was deleted", execution_id=event.execution_id)
            return

        attributes = {
            "execution.status": ExecutionStatus.CANCELLED,
            "execution.lang_and_version": f"{exec_obj.lang}-{exec_obj.lang_version}",
        }
        with self._tracer.start_as_current_span("execution.result", attributes=attributes):
            result = ExecutionResultDomain(
                execution_id=event.execution_id,
                exit_code=None,
                stdout=None,
                stderr=None,
                status=ExecutionStatus.CANCELLED,
            )
            # The API already published the cancel event
            await self._store(result, event.metadata, event.aggregate_id, announce=())

    async def _store(
        self,
        result: ExecutionResultDomain,
        metadata: EventMetadata,
        aggregate_id: str | None,
        announce: tuple[DomainEvent, ...],
    ) -> None:
        """Write the terminal result, then publish the announce events and result_stored.

        Nothing is published when the execution already ended another way, so the failure of a
        cancelled execution's pod neither overwrites the cancel nor notifies anyone. Once the result is
        written, a Kafka error is only logged, so the pod monitor still deletes the pod and frees the slot.
        """
        try:
            written = await self._execution_repo.write_terminal_result(result)
        except PyMongoError as e:
            self.logger.error("Failed to store execution result", execution_id=result.execution_id, exc_info=True)
            await self._publish_result_failed(result.execution_id, str(e), metadata.user_id, aggregate_id)
            return
        if not written:
            self.logger.info(
                "Execution already finished, result not stored",
                execution_id=result.execution_id,
                status=result.status,
            )
            return
        for event in announce:
            await self._producer.produce_or_log(event_to_produce=event, key=result.execution_id)
        await self._publish_result_stored(
            result.execution_id,
            len(result.stdout or "") + len(result.stderr or ""),
            metadata.user_id,
            aggregate_id,
        )

    async def _publish_result_stored(
        self, execution_id: str, size_bytes: int, user_id: str, aggregate_id: str | None
    ) -> None:
        """Publish result stored event."""
        event = ResultStoredEvent(
            execution_id=execution_id,
            aggregate_id=aggregate_id,
            storage_path=execution_id,
            size_bytes=size_bytes,
            storage_type=StorageType.DATABASE,
            metadata=EventMetadata(
                service_name="result-processor",
                service_version="1.0.0",
                user_id=user_id,
            ),
        )
        await self._producer.produce_or_log(event_to_produce=event, key=execution_id)

    async def _publish_result_failed(
        self, execution_id: str, error_message: str, user_id: str, aggregate_id: str | None
    ) -> None:
        """Publish result processing failed event."""
        event = ResultFailedEvent(
            execution_id=execution_id,
            aggregate_id=aggregate_id,
            metadata=EventMetadata(
                service_name="result-processor",
                service_version="1.0.0",
                user_id=user_id,
            ),
        )
        await self._producer.produce(event_to_produce=event, key=execution_id)
