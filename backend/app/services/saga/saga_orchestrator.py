"""Saga Orchestrator - stateless event handler.

Orchestrates saga execution and compensation. Receives events,
processes them, and publishes results. No lifecycle management.
All state is stored in SagaRepository (MongoDB).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from opentelemetry.trace import SpanKind

from app.core.metrics import EventMetrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import get_tracer
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.events.typed import DomainEvent, EventMetadata, SagaCancelledEvent
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import UnifiedProducer

from .base_saga import BaseSaga
from .execution_saga import ExecutionSaga
from .saga_step import SagaContext


class SagaOrchestrator:
    """Stateless saga orchestrator - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    All state stored in SagaRepository. Worker entrypoint handles the consume loop.
    """

    def __init__(
        self,
        config: SagaConfig,
        saga_repository: SagaRepository,
        producer: UnifiedProducer,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: logging.Logger,
        event_metrics: EventMetrics,
    ) -> None:
        self._config = config
        self._repo = saga_repository
        self._producer = producer
        self._alloc_repo = resource_allocation_repository
        self._logger = logger
        self._event_metrics = event_metrics
        self._sagas: dict[str, type[BaseSaga]] = {}

        # Register default sagas
        self._register_default_sagas()

    def register_saga(self, saga_class: type[BaseSaga]) -> None:
        """Register a saga class."""
        self._sagas[saga_class.get_name()] = saga_class
        self._logger.info(f"Registered saga: {saga_class.get_name()}")

    def _register_default_sagas(self) -> None:
        """Register default sagas."""
        self.register_saga(ExecutionSaga)
        self._logger.info("Registered default sagas")

    def get_trigger_event_types(self) -> set[EventType]:
        """Get all event types that trigger sagas.

        Helper for worker entrypoint to know which topics to subscribe to.
        """
        event_types: set[EventType] = set()

        for saga_class in self._sagas.values():
            trigger_events = saga_class.get_trigger_events()
            event_types.update(trigger_events)

        # Also include completion events
        completion_events = {
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
        }
        event_types.update(completion_events)

        return event_types

    async def handle_event(self, event: DomainEvent) -> None:
        """Handle incoming event.

        Called by worker entrypoint for each event.
        """
        self._logger.info(f"Saga orchestrator handling event: type={event.event_type}, id={event.event_id}")

        try:
            # Check if this is a completion event that should update an existing saga
            completion_events = {
                EventType.EXECUTION_COMPLETED,
                EventType.EXECUTION_FAILED,
                EventType.EXECUTION_TIMEOUT,
            }
            if event.event_type in completion_events:
                await self._handle_completion_event(event)
                return

            # Check if this event should trigger a new saga
            saga_triggered = False
            for saga_name, saga_class in self._sagas.items():
                self._logger.debug(f"Checking if {saga_name} should be triggered by {event.event_type}")
                if self._should_trigger_saga(saga_class, event):
                    self._logger.info(f"Event {event.event_type} triggers saga {saga_name}")
                    saga_triggered = True
                    saga_id = await self._start_saga(saga_name, event)
                    if not saga_id:
                        raise RuntimeError(f"Failed to create saga {saga_name} for event {event.event_id}")

            if not saga_triggered:
                self._logger.debug(f"Event {event.event_type} did not trigger any saga")

        except Exception as e:
            self._logger.error(f"Error handling event {event.event_id}: {e}", exc_info=True)
            raise

    async def _handle_completion_event(self, event: DomainEvent) -> None:
        """Handle execution completion events to update saga state."""
        execution_id = getattr(event, "execution_id", None)
        if not execution_id:
            self._logger.warning(f"Completion event {event.event_type} has no execution_id")
            return

        # Find the execution saga specifically
        saga = await self._repo.get_saga_by_execution_and_name(execution_id, ExecutionSaga.get_name())
        if not saga:
            self._logger.debug(f"No execution_saga found for execution {execution_id}")
            return

        # Only update if saga is still in a running state
        if saga.state not in (SagaState.RUNNING, SagaState.CREATED):
            self._logger.debug(f"Saga {saga.saga_id} already in terminal state {saga.state}")
            return

        # Update saga state based on completion event type
        if event.event_type == EventType.EXECUTION_COMPLETED:
            self._logger.info(f"Marking saga {saga.saga_id} as COMPLETED due to execution completion")
            saga.state = SagaState.COMPLETED
            saga.completed_at = datetime.now(UTC)
        elif event.event_type == EventType.EXECUTION_TIMEOUT:
            timeout_seconds = getattr(event, "timeout_seconds", None)
            self._logger.info(f"Marking saga {saga.saga_id} as TIMEOUT after {timeout_seconds}s")
            saga.state = SagaState.TIMEOUT
            saga.error_message = f"Execution timed out after {timeout_seconds} seconds"
            saga.completed_at = datetime.now(UTC)
        else:
            # EXECUTION_FAILED
            error_msg = getattr(event, "error_message", None) or f"Execution {event.event_type}"
            self._logger.info(f"Marking saga {saga.saga_id} as FAILED: {error_msg}")
            saga.state = SagaState.FAILED
            saga.error_message = error_msg
            saga.completed_at = datetime.now(UTC)

        await self._save_saga(saga)

    def _should_trigger_saga(self, saga_class: type[BaseSaga], event: DomainEvent) -> bool:
        """Check if event should trigger a saga."""
        trigger_event_types = saga_class.get_trigger_events()
        should_trigger = event.event_type in trigger_event_types
        self._logger.debug(
            f"Saga {saga_class.get_name()} triggers on {trigger_event_types}, "
            f"event is {event.event_type}, should trigger: {should_trigger}"
        )
        return should_trigger

    async def _start_saga(self, saga_name: str, trigger_event: DomainEvent) -> str | None:
        """Start a new saga instance."""
        self._logger.info(f"Starting saga {saga_name} for event {trigger_event.event_type}")
        saga_class = self._sagas.get(saga_name)
        if not saga_class:
            raise ValueError(f"Unknown saga: {saga_name}")

        execution_id = getattr(trigger_event, "execution_id", None)
        self._logger.debug(f"Extracted execution_id={execution_id} from event")
        if not execution_id:
            self._logger.warning(f"Could not extract execution ID from event: {trigger_event}")
            return None

        existing = await self._repo.get_saga_by_execution_and_name(execution_id, saga_name)
        if existing:
            self._logger.info(f"Saga {saga_name} already exists for execution {execution_id}")
            return existing.saga_id

        instance = Saga(
            saga_id=str(uuid4()),
            saga_name=saga_name,
            execution_id=execution_id,
            state=SagaState.RUNNING,
        )

        await self._save_saga(instance)
        self._logger.info(f"Started saga {saga_name} (ID: {instance.saga_id}) for execution {execution_id}")

        # Execute saga steps synchronously
        saga = saga_class()
        try:
            saga.bind_dependencies(
                producer=self._producer,
                alloc_repo=self._alloc_repo,
                publish_commands=bool(getattr(self._config, "publish_commands", False)),
            )
        except Exception:
            pass

        context = SagaContext(instance.saga_id, execution_id)
        await self._execute_saga(saga, instance, context, trigger_event)

        return instance.saga_id

    async def _execute_saga(
        self,
        saga: BaseSaga,
        instance: Saga,
        context: SagaContext,
        trigger_event: DomainEvent,
    ) -> None:
        """Execute saga steps synchronously."""
        tracer = get_tracer()
        try:
            steps = saga.get_steps()

            for step in steps:
                instance.current_step = step.name
                await self._save_saga(instance)

                self._logger.info(f"Executing saga step: {step.name} for saga {instance.saga_id}")

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
                    self._logger.error(f"Saga step {step.name} failed for saga {instance.saga_id}")

                    if self._config.enable_compensation:
                        await self._compensate_saga(instance, context)
                    else:
                        await self._fail_saga(instance, "Step failed without compensation")
                    return

            # All steps completed
            if instance.saga_name == ExecutionSaga.get_name():
                self._logger.info(f"Saga {instance.saga_id} steps done, waiting for execution completion event")
            else:
                await self._complete_saga(instance)

        except Exception as e:
            self._logger.error(f"Error executing saga {instance.saga_id}: {e}", exc_info=True)

            if self._config.enable_compensation:
                await self._compensate_saga(instance, context)
            else:
                await self._fail_saga(instance, str(e))

    async def _compensate_saga(self, instance: Saga, context: SagaContext) -> None:
        """Execute compensation steps."""
        self._logger.info(f"Starting compensation for saga {instance.saga_id}")

        if instance.state != SagaState.CANCELLED:
            instance.state = SagaState.COMPENSATING
            await self._save_saga(instance)

        for compensation in reversed(context.compensations):
            try:
                self._logger.info(f"Executing compensation: {compensation.name} for saga {instance.saga_id}")
                success = await compensation.compensate(context)

                if success:
                    instance.compensated_steps.append(compensation.name)
                else:
                    self._logger.error(f"Compensation {compensation.name} failed for saga {instance.saga_id}")

            except Exception as e:
                self._logger.error(f"Error in compensation {compensation.name}: {e}", exc_info=True)

        if instance.state == SagaState.CANCELLED:
            instance.updated_at = datetime.now(UTC)
            await self._save_saga(instance)
            self._logger.info(f"Saga {instance.saga_id} compensation completed after cancellation")
        else:
            await self._fail_saga(instance, "Saga compensated due to failure")

    async def _complete_saga(self, instance: Saga) -> None:
        """Mark saga as completed."""
        instance.state = SagaState.COMPLETED
        instance.completed_at = datetime.now(UTC)
        await self._save_saga(instance)
        self._logger.info(f"Saga {instance.saga_id} completed successfully")

    async def _fail_saga(self, instance: Saga, error_message: str) -> None:
        """Mark saga as failed."""
        instance.state = SagaState.FAILED
        instance.error_message = error_message
        instance.completed_at = datetime.now(UTC)
        await self._save_saga(instance)
        self._logger.error(f"Saga {instance.saga_id} failed: {error_message}")

    async def check_timeouts(self) -> int:
        """Check for saga timeouts.

        Should be called periodically from worker entrypoint.
        Returns number of timed out sagas.
        """
        cutoff_time = datetime.now(UTC) - timedelta(seconds=self._config.timeout_seconds)
        timed_out = await self._repo.find_timed_out_sagas(cutoff_time)
        count = 0

        for instance in timed_out:
            self._logger.warning(f"Saga {instance.saga_id} timed out")
            instance.state = SagaState.TIMEOUT
            instance.error_message = f"Saga timed out after {self._config.timeout_seconds} seconds"
            instance.completed_at = datetime.now(UTC)
            await self._save_saga(instance)
            count += 1

        return count

    async def _save_saga(self, instance: Saga) -> None:
        """Persist saga through repository."""
        instance.updated_at = datetime.now(UTC)
        await self._repo.upsert_saga(instance)

    async def get_saga_status(self, saga_id: str) -> Saga | None:
        """Get saga instance status."""
        return await self._repo.get_saga(saga_id)

    async def get_execution_sagas(self, execution_id: str) -> list[Saga]:
        """Get all sagas for an execution."""
        result = await self._repo.get_sagas_by_execution(execution_id)
        return result.sagas

    async def cancel_saga(self, saga_id: str) -> bool:
        """Cancel a running saga and trigger compensation."""
        try:
            saga_instance = await self.get_saga_status(saga_id)
            if not saga_instance:
                self._logger.error("Saga not found", extra={"saga_id": saga_id})
                return False

            if saga_instance.state not in [SagaState.RUNNING, SagaState.CREATED]:
                self._logger.warning(
                    "Cannot cancel saga in current state",
                    extra={"saga_id": saga_id, "state": saga_instance.state},
                )
                return False

            saga_instance.state = SagaState.CANCELLED
            saga_instance.error_message = "Saga cancelled by user request"
            saga_instance.completed_at = datetime.now(UTC)

            user_id = saga_instance.context_data.get("user_id")
            self._logger.info(
                "Saga cancellation initiated",
                extra={
                    "saga_id": saga_id,
                    "execution_id": saga_instance.execution_id,
                    "user_id": user_id,
                },
            )

            await self._save_saga(saga_instance)

            if self._config.store_events:
                await self._publish_saga_cancelled_event(saga_instance)

            if saga_instance.completed_steps and self._config.enable_compensation:
                saga_class = self._sagas.get(saga_instance.saga_name)
                if saga_class:
                    saga = saga_class()
                    try:
                        saga.bind_dependencies(
                            producer=self._producer,
                            alloc_repo=self._alloc_repo,
                            publish_commands=bool(getattr(self._config, "publish_commands", False)),
                        )
                    except Exception:
                        pass

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
                else:
                    self._logger.error(
                        "Saga class not found for compensation",
                        extra={"saga_name": saga_instance.saga_name, "saga_id": saga_id},
                    )

            self._logger.info("Saga cancelled successfully", extra={"saga_id": saga_id})
            return True

        except Exception as e:
            self._logger.error(
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

            await self._producer.produce(event_to_produce=event, key=saga_instance.execution_id)
            self._logger.info(f"Published cancellation event for saga {saga_instance.saga_id}")

        except Exception as e:
            self._logger.error(f"Failed to publish saga cancellation event: {e}")
