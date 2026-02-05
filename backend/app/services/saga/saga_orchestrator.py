import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from opentelemetry.trace import SpanKind

from app.core.tracing import EventAttributes
from app.core.tracing.utils import get_tracer
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.saga import SagaState
from app.domain.events.typed import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    ExecutionTimeoutEvent,
    SagaCancelledEvent,
)
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import EventPublisher

from .execution_saga import ExecutionSaga
from .saga_step import SagaContext

_SAGA_NAME = ExecutionSaga.get_name()


class SagaOrchestrator:
    """Orchestrates saga execution and compensation.

    Idempotency is handled by FastStream middleware (IdempotencyMiddleware).
    """

    def __init__(
        self,
        config: SagaConfig,
        saga_repository: SagaRepository,
        producer: EventPublisher,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: logging.Logger,
    ):
        self.config = config
        self._producer = producer
        self._repo: SagaRepository = saga_repository
        self._alloc_repo: ResourceAllocationRepository = resource_allocation_repository
        self.logger = logger

    async def handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Handle EXECUTION_REQUESTED — starts a new saga."""
        await self._start_saga(event)

    async def handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle EXECUTION_COMPLETED — marks saga as completed."""
        await self._resolve_completion(event.execution_id, SagaState.COMPLETED)

    async def handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle EXECUTION_FAILED — marks saga as failed."""
        await self._resolve_completion(
            event.execution_id, SagaState.FAILED, event.error_message or "Execution failed"
        )

    async def handle_execution_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Handle EXECUTION_TIMEOUT — marks saga as timed out."""
        await self._resolve_completion(
            event.execution_id, SagaState.TIMEOUT, f"Execution timed out after {event.timeout_seconds} seconds"
        )

    async def _resolve_completion(
        self, execution_id: str, state: SagaState, error_message: str | None = None
    ) -> None:
        """Look up the active saga for an execution and transition it to a terminal state."""
        saga = await self._repo.get_saga_by_execution_and_name(execution_id, _SAGA_NAME)
        if not saga:
            self.logger.debug(f"No execution_saga found for execution {execution_id}")
            return

        if saga.state not in (SagaState.RUNNING, SagaState.CREATED):
            self.logger.debug(f"Saga {saga.saga_id} already in terminal state {saga.state}")
            return

        self.logger.info(f"Marking saga {saga.saga_id} as {state}")
        saga.state = state
        saga.error_message = error_message
        saga.completed_at = datetime.now(UTC)
        await self._save_saga(saga)

    async def _start_saga(self, trigger_event: ExecutionRequestedEvent) -> str:
        """Start a new saga instance."""
        execution_id = trigger_event.execution_id
        self.logger.info(f"Starting saga {_SAGA_NAME} for execution {execution_id}")

        candidate = Saga(
            saga_id=str(uuid4()),
            saga_name=_SAGA_NAME,
            execution_id=execution_id,
            state=SagaState.RUNNING,
        )

        instance, created = await self._repo.get_or_create_saga(candidate)
        if not created:
            self.logger.info(f"Saga {_SAGA_NAME} already exists for execution {execution_id}")
            return instance.saga_id

        self.logger.info(f"Started saga {_SAGA_NAME} (ID: {instance.saga_id}) for execution {execution_id}")

        saga = self._create_saga_instance()
        context = SagaContext(instance.saga_id, execution_id)

        await self._execute_saga(saga, instance, context, trigger_event)

        return instance.saga_id

    def _create_saga_instance(self) -> ExecutionSaga:
        """Create and bind an ExecutionSaga instance."""
        saga = ExecutionSaga()
        saga.bind_dependencies(
            producer=self._producer,
            alloc_repo=self._alloc_repo,
            publish_commands=self.config.publish_commands,
        )
        return saga

    async def _execute_saga(
        self,
        saga: ExecutionSaga,
        instance: Saga,
        context: SagaContext,
        trigger_event: ExecutionRequestedEvent,
    ) -> None:
        """Execute saga steps."""
        tracer = get_tracer()
        try:
            steps = saga.get_steps()

            for step in steps:
                instance.current_step = step.name
                await self._save_saga(instance)

                self.logger.info(f"Executing saga step: {step.name} for saga {instance.saga_id}")

                with tracer.start_as_current_span(
                    name="saga.step",
                    kind=SpanKind.INTERNAL,
                    attributes={
                        str(EventAttributes.SAGA_NAME): instance.saga_name,
                        str(EventAttributes.SAGA_ID): instance.saga_id,
                        str(EventAttributes.SAGA_STEP): step.name,
                        str(EventAttributes.EXECUTION_ID): instance.execution_id,
                    },
                ):
                    success = await step.execute(context, trigger_event)

                if success:
                    instance.completed_steps.append(step.name)
                    instance.context_data = context.to_public_dict()
                    await self._save_saga(instance)

                    compensation = step.get_compensation()
                    if compensation:
                        context.add_compensation(compensation)
                else:
                    self.logger.error(f"Saga step {step.name} failed for saga {instance.saga_id}")

                    if self.config.enable_compensation:
                        await self._compensate_saga(instance, context)
                    else:
                        await self._fail_saga(instance, "Step failed without compensation")

                    return

            self.logger.info(f"Saga {instance.saga_id} steps done, waiting for execution completion event")

        except Exception as e:
            self.logger.error(f"Error executing saga {instance.saga_id}: {e}", exc_info=True)

            if self.config.enable_compensation:
                await self._compensate_saga(instance, context)
            else:
                await self._fail_saga(instance, str(e))

    async def _compensate_saga(self, instance: Saga, context: SagaContext) -> None:
        """Execute compensation steps."""
        self.logger.info(f"Starting compensation for saga {instance.saga_id}")

        if instance.state != SagaState.CANCELLED:
            instance.state = SagaState.COMPENSATING
            await self._save_saga(instance)

        for compensation in reversed(context.compensations):
            try:
                self.logger.info(f"Executing compensation: {compensation.name} for saga {instance.saga_id}")

                success = await compensation.compensate(context)

                if success:
                    instance.compensated_steps.append(compensation.name)
                else:
                    self.logger.error(f"Compensation {compensation.name} failed for saga {instance.saga_id}")

            except Exception as e:
                self.logger.error(f"Error in compensation {compensation.name}: {e}", exc_info=True)

        if instance.state == SagaState.CANCELLED:
            instance.updated_at = datetime.now(UTC)
            await self._save_saga(instance)
            self.logger.info(f"Saga {instance.saga_id} compensation completed after cancellation")
        else:
            await self._fail_saga(instance, "Saga compensated due to failure")

    async def _fail_saga(self, instance: Saga, error_message: str) -> None:
        """Mark saga as failed."""
        instance.state = SagaState.FAILED
        instance.error_message = error_message
        instance.completed_at = datetime.now(UTC)
        await self._save_saga(instance)
        self.logger.error(f"Saga {instance.saga_id} failed: {error_message}")

    async def check_timeouts(self) -> None:
        """Check for timed-out sagas and mark them. Single invocation."""
        cutoff_time = datetime.now(UTC) - timedelta(seconds=self.config.timeout_seconds)
        timed_out = await self._repo.find_timed_out_sagas(cutoff_time)
        for instance in timed_out:
            self.logger.warning(f"Saga {instance.saga_id} timed out")
            instance.state = SagaState.TIMEOUT
            instance.error_message = f"Saga timed out after {self.config.timeout_seconds} seconds"
            instance.completed_at = datetime.now(UTC)
            await self._save_saga(instance)

    async def _save_saga(self, instance: Saga) -> None:
        """Persist saga through repository."""
        instance.updated_at = datetime.now(UTC)
        await self._repo.upsert_saga(instance)

    async def get_saga_status(self, saga_id: str) -> Saga | None:
        """Get saga instance status."""
        return await self._repo.get_saga(saga_id)

    async def get_execution_sagas(self, execution_id: str) -> list[Saga]:
        """Get all sagas for an execution, sorted by created_at descending (newest first)."""
        result = await self._repo.get_sagas_by_execution(execution_id)
        return result.sagas

    async def cancel_saga(self, saga_id: str) -> bool:
        """Cancel a running saga and trigger compensation."""
        try:
            saga_instance = await self.get_saga_status(saga_id)
            if not saga_instance:
                self.logger.error("Saga not found", extra={"saga_id": saga_id})
                return False

            if saga_instance.state not in [SagaState.RUNNING, SagaState.CREATED]:
                self.logger.warning(
                    "Cannot cancel saga in current state. Only RUNNING or CREATED sagas can be cancelled.",
                    extra={"saga_id": saga_id, "state": saga_instance.state},
                )
                return False

            saga_instance.state = SagaState.CANCELLED
            saga_instance.error_message = "Saga cancelled by user request"
            saga_instance.completed_at = datetime.now(UTC)

            user_id = saga_instance.context_data.get("user_id")
            self.logger.info(
                "Saga cancellation initiated",
                extra={
                    "saga_id": saga_id,
                    "execution_id": saga_instance.execution_id,
                    "user_id": user_id,
                },
            )

            await self._save_saga(saga_instance)

            if self._producer and self.config.store_events:
                await self._publish_saga_cancelled_event(saga_instance)

            if saga_instance.completed_steps and self.config.enable_compensation:
                saga = self._create_saga_instance()
                context = SagaContext(saga_instance.saga_id, saga_instance.execution_id)

                for key, value in saga_instance.context_data.items():
                    context.set(key, value)

                steps = saga.get_steps()
                for step in steps:
                    if step.name in saga_instance.completed_steps:
                        compensation = step.get_compensation()
                        if compensation:
                            context.add_compensation(compensation)

                await self._compensate_saga(saga_instance, context)

            self.logger.info("Saga cancelled successfully", extra={"saga_id": saga_id})
            return True

        except Exception as e:
            self.logger.error(
                "Error cancelling saga",
                extra={"saga_id": saga_id, "error": str(e)},
                exc_info=True,
            )
            return False

    async def _publish_saga_cancelled_event(self, saga_instance: Saga) -> None:
        """Publish saga cancelled event."""
        try:
            cancelled_by = saga_instance.context_data.get("user_id") if saga_instance.context_data else None
            metadata = EventMetadata(
                service_name="saga-orchestrator",
                service_version="1.0.0",
                user_id=cancelled_by or "system",
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
                await self._producer.publish(event=event, key=saga_instance.execution_id)

            self.logger.info(f"Published cancellation event for saga {saga_instance.saga_id}")

        except Exception as e:
            self.logger.error(f"Failed to publish saga cancellation event: {e}")
