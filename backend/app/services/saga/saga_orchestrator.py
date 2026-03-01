import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import structlog
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from app.db.repositories import ResourceAllocationRepository, SagaRepository
from app.domain.enums import SagaState
from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    ExecutionTimeoutEvent,
    SagaCancelledEvent,
    SagaStartedEvent,
)
from app.domain.saga import (
    Saga,
    SagaConcurrencyError,
    SagaConfig,
    SagaContextData,
)
from app.events.core import UnifiedProducer
from app.services.execution_queue import ExecutionQueueService
from app.services.runtime_settings import RuntimeSettingsLoader

from .execution_saga import ExecutionSaga
from .saga_step import SagaContext

_SAGA_NAME = ExecutionSaga.get_name()


class SagaOrchestrator:
    """Orchestrates saga execution and compensation."""

    def __init__(
        self,
        config: SagaConfig,
        saga_repository: SagaRepository,
        producer: UnifiedProducer,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: structlog.stdlib.BoundLogger,
        queue_service: ExecutionQueueService,
        runtime_settings: RuntimeSettingsLoader,
    ):
        self.config = config
        self._producer = producer
        self._repo: SagaRepository = saga_repository
        self._alloc_repo: ResourceAllocationRepository = resource_allocation_repository
        self.logger = logger
        self._queue = queue_service
        self._runtime_settings = runtime_settings

    async def handle_execution_requested(self, event: DomainEvent) -> None:
        """Handle EXECUTION_REQUESTED — enqueue and attempt to schedule."""
        if not isinstance(event, ExecutionRequestedEvent):
            raise TypeError(f"Expected ExecutionRequestedEvent, got {type(event).__name__}")
        await self._queue.enqueue(event)
        await self.try_schedule_from_queue()

    async def handle_execution_completed(self, event: DomainEvent) -> None:
        """Handle EXECUTION_COMPLETED — marks saga as completed."""
        if not isinstance(event, ExecutionCompletedEvent):
            raise TypeError(f"Expected ExecutionCompletedEvent, got {type(event).__name__}")
        await self._resolve_completion(event.execution_id, SagaState.COMPLETED)

    async def handle_execution_failed(self, event: DomainEvent) -> None:
        """Handle EXECUTION_FAILED — marks saga as failed."""
        if not isinstance(event, ExecutionFailedEvent):
            raise TypeError(f"Expected ExecutionFailedEvent, got {type(event).__name__}")
        await self._resolve_completion(
            event.execution_id, SagaState.FAILED, f"{event.error_type} (exit code {event.exit_code})"
        )

    async def handle_execution_timeout(self, event: DomainEvent) -> None:
        """Handle EXECUTION_TIMEOUT — marks saga as timed out."""
        if not isinstance(event, ExecutionTimeoutEvent):
            raise TypeError(f"Expected ExecutionTimeoutEvent, got {type(event).__name__}")
        await self._resolve_completion(
            event.execution_id, SagaState.TIMEOUT, f"Execution timed out after {event.timeout_seconds} seconds"
        )

    async def handle_execution_cancelled(self, event: DomainEvent) -> None:
        """Handle EXECUTION_CANCELLED — remove from queue and mark saga as cancelled."""
        if not isinstance(event, ExecutionCancelledEvent):
            raise TypeError(f"Expected ExecutionCancelledEvent, got {type(event).__name__}")
        await self._queue.remove(event.execution_id)
        await self._resolve_completion(
            event.execution_id, SagaState.CANCELLED, f"cancelled by {event.cancelled_by}"
        )

    async def _resolve_completion(
        self, execution_id: str, state: SagaState, error_message: str | None = None
    ) -> None:
        """Look up the active saga for an execution and transition it to a terminal state.

        Always releases the queue slot and attempts to schedule the next pending
        execution, even when no saga is found or the saga is already terminal.
        ``release()`` is idempotent (Redis SREM on a missing member is a no-op).
        """
        saga = await self._repo.get_saga_by_execution_and_name(execution_id, _SAGA_NAME)
        if not saga:
            self.logger.debug("No execution_saga found for execution", execution_id=execution_id)
        elif saga.state.is_terminal:
            self.logger.debug("Saga already in terminal state", saga_id=saga.saga_id, state=saga.state)
        else:
            self.logger.info("Marking saga terminal state", saga_id=saga.saga_id, state=state)
            await self._repo.save_saga(
                saga.saga_id, state=state, error_message=error_message, completed_at=datetime.now(UTC),
            )

        await self._queue.release(execution_id)
        await self.try_schedule_from_queue()

    _MAX_SAGA_START_RETRIES = 3

    async def try_schedule_from_queue(self) -> None:
        """Try to schedule pending executions from the queue."""
        settings = await self._runtime_settings.get_effective_settings()
        while True:
            result = await self._queue.try_schedule(settings.max_concurrent_executions)
            if result is None:
                break
            execution_id, event = result
            try:
                await self._start_saga(event)
            except Exception:
                retry_count = await self._queue.increment_retry_count(execution_id)
                self.logger.error(
                    "Failed to start saga",
                    execution_id=execution_id,
                    retry_count=retry_count,
                    exc_info=True,
                )
                await self._queue.release(execution_id)
                if retry_count >= self._MAX_SAGA_START_RETRIES:
                    self.logger.error(
                        "Max saga start retries exceeded, dropping execution",
                        execution_id=execution_id,
                    )
                    await self._resolve_completion(
                        execution_id, SagaState.FAILED,
                        f"Failed to start saga after {retry_count} attempts",
                    )
                else:
                    await self._queue.enqueue(event)
                break

    async def _start_saga(self, trigger_event: ExecutionRequestedEvent) -> str:
        """Start a new saga instance."""
        execution_id = trigger_event.execution_id
        self.logger.info("Starting saga", saga_name=_SAGA_NAME, execution_id=execution_id)

        candidate = Saga(
            saga_id=str(uuid4()),
            saga_name=_SAGA_NAME,
            execution_id=execution_id,
            state=SagaState.RUNNING,
        )

        instance, created = await self._repo.get_or_create_saga(candidate)
        if not created:
            self.logger.info("Saga already exists for execution", saga_name=_SAGA_NAME, execution_id=execution_id)
            return instance.saga_id

        self.logger.info("Started saga", saga_name=_SAGA_NAME, saga_id=instance.saga_id, execution_id=execution_id)

        if self._producer and self.config.store_events:
            await self._publish_saga_started_event(instance, trigger_event)

        saga = self._create_saga_instance()
        context = SagaContext(instance.saga_id, execution_id)
        context.set("user_id", trigger_event.metadata.user_id)

        await self._execute_saga(saga, instance, context, trigger_event)

        return instance.saga_id

    def _create_saga_instance(self) -> ExecutionSaga:
        """Create and bind an ExecutionSaga instance."""
        saga = ExecutionSaga()
        saga.bind_dependencies(
            producer=self._producer,
            alloc_repo=self._alloc_repo,
            publish_commands=self.config.publish_commands,
            logger=self.logger,
        )
        return saga

    async def _execute_saga(
        self,
        saga: ExecutionSaga,
        instance: Saga,
        context: SagaContext,
        trigger_event: DomainEvent,
    ) -> None:
        """Execute saga steps."""
        tracer = trace.get_tracer(__name__)
        try:
            steps = saga.get_steps()

            for step in steps:
                saved = await self._repo.save_saga(instance.saga_id, current_step=step.name)

                if saved.state.is_terminal:
                    self.logger.info(
                        "Saga no longer active, stopping", saga_id=instance.saga_id, state=saved.state
                    )
                    return

                self.logger.info("Executing saga step", step=step.name, saga_id=instance.saga_id)

                with tracer.start_as_current_span(
                    name="saga.step",
                    kind=SpanKind.INTERNAL,
                    attributes={
                        "saga.name": instance.saga_name,
                        "saga.id": instance.saga_id,
                        "saga.step": step.name,
                        "execution.id": instance.execution_id,
                    },
                ):
                    success = await step.execute(context, trigger_event)

                if success:
                    await self._repo.save_saga(
                        instance.saga_id,
                        completed_steps=[*saved.completed_steps, step.name],
                        context_data=SagaContextData(**{
                            k: v for k, v in context.data.items() if k in SagaContextData.__dataclass_fields__
                        }),
                    )

                    compensation = step.get_compensation()
                    if compensation:
                        context.add_compensation(compensation)
                else:
                    self.logger.error("Saga step failed", step=step.name, saga_id=instance.saga_id)

                    if self.config.enable_compensation:
                        await self._compensate_saga(instance.saga_id, context)
                    else:
                        await self._fail_saga(instance.saga_id, "Step failed without compensation")

                    return

            self.logger.info("Saga steps done, waiting for execution completion event", saga_id=instance.saga_id)

        except SagaConcurrencyError:
            self.logger.info("Saga modified concurrently, stopping execution", saga_id=instance.saga_id)
        except Exception as e:
            self.logger.error("Error executing saga", saga_id=instance.saga_id, exc_info=True)

            if self.config.enable_compensation:
                await self._compensate_saga(instance.saga_id, context)
            else:
                await self._fail_saga(instance.saga_id, str(e))

    async def _compensate_saga(self, saga_id: str, context: SagaContext) -> None:
        """Execute compensation steps."""
        self.logger.info("Starting compensation for saga", saga_id=saga_id)

        saga = await self._repo.get_saga(saga_id)
        if not saga:
            self.logger.error("Cannot compensate: saga not found", saga_id=saga_id)
            return

        was_cancelled = saga.state == SagaState.CANCELLED

        if not was_cancelled:
            await self._repo.save_saga(saga_id, state=SagaState.COMPENSATING)

        compensated: list[str] = list(saga.compensated_steps)
        failed_compensations: list[str] = []
        for compensation in reversed(context.compensations):
            try:
                self.logger.info("Executing compensation", compensation=compensation.name, saga_id=saga_id)

                success = await compensation.compensate(context)

                if success:
                    compensated.append(compensation.name)
                else:
                    failed_compensations.append(compensation.name)
                    self.logger.error("Compensation failed", compensation=compensation.name, saga_id=saga_id)

            except Exception:
                failed_compensations.append(compensation.name)
                self.logger.error(
                    "Error in compensation", compensation=compensation.name, saga_id=saga_id, exc_info=True
                )

        if failed_compensations:
            self.logger.error(
                "Partial compensation — some steps could not be undone",
                saga_id=saga_id,
                failed_compensations=failed_compensations,
            )

        if was_cancelled:
            await self._repo.save_saga(saga_id, compensated_steps=compensated)
            self.logger.info("Saga compensation completed after cancellation", saga_id=saga_id)
        else:
            await self._repo.save_saga(
                saga_id,
                state=SagaState.FAILED,
                error_message="Saga compensated due to failure",
                completed_at=datetime.now(UTC),
                compensated_steps=compensated,
            )
            self.logger.error("Saga failed after compensation", saga_id=saga_id)

    async def _fail_saga(self, saga_id: str, error_message: str) -> None:
        """Mark saga as failed."""
        await self._repo.save_saga(
            saga_id, state=SagaState.FAILED, error_message=error_message, completed_at=datetime.now(UTC),
        )
        self.logger.error("Saga failed", saga_id=saga_id, error_message=error_message)

    async def check_timeouts(self) -> None:
        """Check for timed-out sagas and mark them. Single invocation."""
        cutoff_time = datetime.now(UTC) - timedelta(seconds=self.config.timeout_seconds)
        timed_out = await self._repo.find_timed_out_sagas(cutoff_time)
        for instance in timed_out:
            self.logger.warning("Saga timed out", saga_id=instance.saga_id)
            await self._repo.save_saga(
                instance.saga_id,
                state=SagaState.TIMEOUT,
                error_message=f"Saga timed out after {self.config.timeout_seconds} seconds",
                completed_at=datetime.now(UTC),
            )

    async def get_saga_status(self, saga_id: str) -> Saga | None:
        """Get saga instance status."""
        return await self._repo.get_saga(saga_id)

    async def get_execution_sagas(self, execution_id: str) -> list[Saga]:
        """Get all sagas for an execution, sorted by created_at descending (newest first)."""
        result = await self._repo.get_sagas_by_execution(execution_id)
        return result.sagas

    async def cancel_saga(self, saga_id: str) -> None:
        """Cancel a running saga and trigger compensation.

        Uses an atomic findOneAndUpdate to set state=CANCELLED, eliminating
        revision-check races with the step-execution loop.

        Raises SagaNotFoundError if saga doesn't exist.
        Raises SagaInvalidStateError if saga is not in a cancellable state.
        """
        saved = await self._repo.atomic_cancel_saga(
            saga_id,
            error_message="Saga cancelled by user request",
            completed_at=datetime.now(UTC),
        )

        self.logger.info(
            "Saga cancellation initiated",
            saga_id=saga_id,
            execution_id=saved.execution_id,
            user_id=saved.context_data.user_id,
        )

        if self._producer and self.config.store_events:
            await self._publish_saga_cancelled_event(saved)

        if saved.completed_steps and self.config.enable_compensation:
            saga = self._create_saga_instance()
            context = SagaContext(saved.saga_id, saved.execution_id)

            for key, value in dataclasses.asdict(saved.context_data).items():
                context.set(key, value)

            steps = saga.get_steps()
            for step in steps:
                if step.name in saved.completed_steps:
                    compensation = step.get_compensation()
                    if compensation:
                        context.add_compensation(compensation)

            await self._compensate_saga(saga_id, context)

        self.logger.info("Saga cancelled successfully", saga_id=saga_id)

    async def _publish_saga_started_event(
        self, instance: Saga, trigger_event: ExecutionRequestedEvent,
    ) -> None:
        """Publish saga started event after the document is persisted."""
        try:
            event = SagaStartedEvent(
                saga_id=instance.saga_id,
                saga_name=instance.saga_name,
                execution_id=instance.execution_id,
                initial_event_id=trigger_event.event_id,
                metadata=EventMetadata(
                    service_name="saga-orchestrator",
                    service_version="1.0.0",
                    user_id=trigger_event.metadata.user_id,
                ),
            )
            await self._producer.produce(event_to_produce=event, key=instance.execution_id)
            self.logger.info("Published SagaStartedEvent", saga_id=instance.saga_id)
        except Exception:
            self.logger.error("Failed to publish saga started event", exc_info=True)

    async def _publish_saga_cancelled_event(self, saga_instance: Saga) -> None:
        """Publish saga cancelled event."""
        try:
            cancelled_by = saga_instance.context_data.user_id
            metadata = EventMetadata(
                service_name="saga-orchestrator",
                service_version="1.0.0",
                user_id=cancelled_by,
            )

            event = SagaCancelledEvent(
                saga_id=saga_instance.saga_id,
                saga_name=saga_instance.saga_name,
                execution_id=saga_instance.execution_id,
                reason=saga_instance.error_message or "User requested cancellation",
                completed_steps=saga_instance.completed_steps,
                compensated_steps=saga_instance.compensated_steps,
                cancelled_at=saga_instance.completed_at,
                cancelled_by=cancelled_by,
                metadata=metadata,
            )

            if self._producer:
                await self._producer.produce(event_to_produce=event, key=saga_instance.execution_id)

            self.logger.info("Published cancellation event", saga_id=saga_instance.saga_id)

        except Exception:
            self.logger.error("Failed to publish saga cancellation event", exc_info=True)
