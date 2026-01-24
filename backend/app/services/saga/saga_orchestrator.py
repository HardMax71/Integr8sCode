import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from opentelemetry.trace import SpanKind

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics import EventMetrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import get_tracer
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.events.typed import DomainEvent, EventMetadata, SagaCancelledEvent
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.mappings import get_topic_for_event
from app.services.idempotency import IdempotentConsumerWrapper
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.settings import Settings

from .base_saga import BaseSaga
from .execution_saga import ExecutionSaga
from .saga_step import SagaContext


class SagaOrchestrator(LifecycleEnabled):
    """Orchestrates saga execution and compensation"""

    def __init__(
        self,
        config: SagaConfig,
        saga_repository: SagaRepository,
        producer: UnifiedProducer,
        schema_registry_manager: SchemaRegistryManager,
        settings: Settings,
        event_store: EventStore,
        idempotency_manager: IdempotencyManager,
        resource_allocation_repository: ResourceAllocationRepository,
        logger: logging.Logger,
        event_metrics: EventMetrics,
    ):
        super().__init__()
        self.config = config
        self._sagas: dict[str, type[BaseSaga]] = {}
        self._running_instances: dict[str, Saga] = {}
        self._consumer: IdempotentConsumerWrapper | None = None
        self._idempotency_manager: IdempotencyManager = idempotency_manager
        self._producer = producer
        self._schema_registry_manager = schema_registry_manager
        self._settings = settings
        self._event_store = event_store
        self._repo: SagaRepository = saga_repository
        self._alloc_repo: ResourceAllocationRepository = resource_allocation_repository
        self._tasks: list[asyncio.Task[None]] = []
        self.logger = logger
        self._event_metrics = event_metrics

    def register_saga(self, saga_class: type[BaseSaga]) -> None:
        self._sagas[saga_class.get_name()] = saga_class
        self.logger.info(f"Registered saga: {saga_class.get_name()}")

    def _register_default_sagas(self) -> None:
        self.register_saga(ExecutionSaga)
        self.logger.info("Registered default sagas")

    async def _on_start(self) -> None:
        """Start the saga orchestrator."""
        self.logger.info(f"Starting saga orchestrator: {self.config.name}")

        self._register_default_sagas()

        await self._start_consumer()

        timeout_task = asyncio.create_task(self._check_timeouts())
        self._tasks.append(timeout_task)

        self.logger.info("Saga orchestrator started")

    async def _on_stop(self) -> None:
        """Stop the saga orchestrator."""
        self.logger.info("Stopping saga orchestrator...")

        if self._consumer:
            await self._consumer.stop()

        await self._idempotency_manager.close()

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self.logger.info("Saga orchestrator stopped")

    async def _start_consumer(self) -> None:
        self.logger.info(f"Registered sagas: {list(self._sagas.keys())}")
        topics = set()
        event_types_to_register = set()

        for saga_class in self._sagas.values():
            trigger_event_types = saga_class.get_trigger_events()
            self.logger.info(f"Saga {saga_class.get_name()} triggers on event types: {trigger_event_types}")

            # Convert event types to topics for subscription
            for event_type in trigger_event_types:
                topic = get_topic_for_event(event_type)
                topics.add(topic)
                event_types_to_register.add(event_type)
                self.logger.debug(f"Event type {event_type} maps to topic {topic}")

        # Also register handlers for completion events so execution sagas can complete
        completion_event_types = {
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
        }
        for event_type in completion_event_types:
            topic = get_topic_for_event(event_type)
            topics.add(topic)
            event_types_to_register.add(event_type)
            self.logger.debug(f"Completion event type {event_type} maps to topic {topic}")

        if not topics:
            self.logger.warning("No trigger events found in registered sagas")
            return

        consumer_config = ConsumerConfig(
            bootstrap_servers=self._settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"saga-{self.config.name}",
            enable_auto_commit=False,
            session_timeout_ms=self._settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self._settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            max_poll_interval_ms=self._settings.KAFKA_MAX_POLL_INTERVAL_MS,
            request_timeout_ms=self._settings.KAFKA_REQUEST_TIMEOUT_MS,
        )

        dispatcher = EventDispatcher(logger=self.logger)
        for event_type in event_types_to_register:
            dispatcher.register_handler(event_type, self._handle_event)
            self.logger.info(f"Registered handler for event type: {event_type}")

        base_consumer = UnifiedConsumer(
            config=consumer_config,
            event_dispatcher=dispatcher,
            schema_registry=self._schema_registry_manager,
            settings=self._settings,
            logger=self.logger,
            event_metrics=self._event_metrics,
        )
        self._consumer = IdempotentConsumerWrapper(
            consumer=base_consumer,
            idempotency_manager=self._idempotency_manager,
            dispatcher=dispatcher,
            logger=self.logger,
            default_key_strategy="event_based",
            default_ttl_seconds=7200,
            enable_for_all_handlers=False,
        )

        assert self._consumer is not None
        await self._consumer.start(list(topics))

        self.logger.info(f"Saga consumer started for topics: {topics}")

    async def _handle_event(self, event: DomainEvent) -> None:
        """Handle incoming event"""
        self.logger.info(f"Saga orchestrator handling event: type={event.event_type}, id={event.event_id}")
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
                self.logger.debug(f"Checking if {saga_name} should be triggered by {event.event_type}")
                if self._should_trigger_saga(saga_class, event):
                    self.logger.info(f"Event {event.event_type} triggers saga {saga_name}")
                    saga_triggered = True
                    saga_id = await self._start_saga(saga_name, event)
                    if not saga_id:
                        raise RuntimeError(f"Failed to create saga {saga_name} for event {event.event_id}")

            if not saga_triggered:
                self.logger.debug(f"Event {event.event_type} did not trigger any saga")

        except Exception as e:
            self.logger.error(f"Error handling event {event.event_id}: {e}", exc_info=True)
            raise

    async def _handle_completion_event(self, event: DomainEvent) -> None:
        """Handle execution completion events to update saga state."""
        execution_id = getattr(event, "execution_id", None)
        if not execution_id:
            self.logger.warning(f"Completion event {event.event_type} has no execution_id")
            return

        # Find the execution saga specifically (not other saga types)
        saga = await self._repo.get_saga_by_execution_and_name(execution_id, ExecutionSaga.get_name())
        if not saga:
            self.logger.debug(f"No execution_saga found for execution {execution_id}")
            return

        # Only update if saga is still in a running state
        if saga.state not in (SagaState.RUNNING, SagaState.CREATED):
            self.logger.debug(f"Saga {saga.saga_id} already in terminal state {saga.state}")
            return

        # Update saga state based on completion event type
        if event.event_type == EventType.EXECUTION_COMPLETED:
            self.logger.info(f"Marking saga {saga.saga_id} as COMPLETED due to execution completion")
            saga.state = SagaState.COMPLETED
            saga.completed_at = datetime.now(UTC)
        elif event.event_type == EventType.EXECUTION_TIMEOUT:
            timeout_seconds = getattr(event, "timeout_seconds", None)
            self.logger.info(f"Marking saga {saga.saga_id} as TIMEOUT after {timeout_seconds}s")
            saga.state = SagaState.TIMEOUT
            saga.error_message = f"Execution timed out after {timeout_seconds} seconds"
            saga.completed_at = datetime.now(UTC)
        else:
            # EXECUTION_FAILED
            error_msg = getattr(event, "error_message", None) or f"Execution {event.event_type}"
            self.logger.info(f"Marking saga {saga.saga_id} as FAILED: {error_msg}")
            saga.state = SagaState.FAILED
            saga.error_message = error_msg
            saga.completed_at = datetime.now(UTC)

        await self._save_saga(saga)
        self._running_instances.pop(saga.saga_id, None)

    def _should_trigger_saga(self, saga_class: type[BaseSaga], event: DomainEvent) -> bool:
        trigger_event_types = saga_class.get_trigger_events()
        should_trigger = event.event_type in trigger_event_types
        self.logger.debug(
            f"Saga {saga_class.get_name()} triggers on {trigger_event_types}, "
            f"event is {event.event_type}, should trigger: {should_trigger}"
        )
        return should_trigger

    async def _start_saga(self, saga_name: str, trigger_event: DomainEvent) -> str | None:
        """Start a new saga instance"""
        self.logger.info(f"Starting saga {saga_name} for event {trigger_event.event_type}")
        saga_class = self._sagas.get(saga_name)
        if not saga_class:
            raise ValueError(f"Unknown saga: {saga_name}")

        execution_id = getattr(trigger_event, "execution_id", None)
        self.logger.debug(f"Extracted execution_id={execution_id} from event")
        if not execution_id:
            self.logger.warning(f"Could not extract execution ID from event: {trigger_event}")
            return None

        existing = await self._repo.get_saga_by_execution_and_name(execution_id, saga_name)
        if existing:
            self.logger.info(f"Saga {saga_name} already exists for execution {execution_id}")
            saga_id: str = existing.saga_id
            return saga_id

        instance = Saga(
            saga_id=str(uuid4()),
            saga_name=saga_name,
            execution_id=execution_id,
            state=SagaState.RUNNING,
        )

        await self._save_saga(instance)
        self._running_instances[instance.saga_id] = instance

        self.logger.info(f"Started saga {saga_name} (ID: {instance.saga_id}) for execution {execution_id}")

        saga = saga_class()
        # Inject runtime dependencies explicitly (no DI via context)
        try:
            saga.bind_dependencies(
                producer=self._producer,
                alloc_repo=self._alloc_repo,
                publish_commands=bool(getattr(self.config, "publish_commands", False)),
            )
        except Exception:
            # Back-compat: if saga doesn't support binding, it will fallback to context where needed
            pass

        context = SagaContext(instance.saga_id, execution_id)

        asyncio.create_task(self._execute_saga(saga, instance, context, trigger_event))

        return instance.saga_id

    async def _execute_saga(
        self,
        saga: BaseSaga,
        instance: Saga,
        context: SagaContext,
        trigger_event: DomainEvent,
    ) -> None:
        """Execute saga steps"""
        tracer = get_tracer()
        try:
            # Get saga steps
            steps = saga.get_steps()

            # Execute each step
            for step in steps:
                if not self.is_running:
                    break

                # Update current step
                instance.current_step = step.name
                await self._save_saga(instance)

                self.logger.info(f"Executing saga step: {step.name} for saga {instance.saga_id}")

                # Execute step within a span
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

                    # Persist only safe, public context (no ephemeral objects)
                    instance.context_data = context.to_public_dict()
                    await self._save_saga(instance)

                    compensation = step.get_compensation()
                    if compensation:
                        context.add_compensation(compensation)
                else:
                    # Step failed, start compensation
                    self.logger.error(f"Saga step {step.name} failed for saga {instance.saga_id}")

                    if self.config.enable_compensation:
                        await self._compensate_saga(instance, context)
                    else:
                        await self._fail_saga(instance, "Step failed without compensation")

                    return

            # All steps completed successfully
            # Execution saga waits for external completion events (EXECUTION_COMPLETED/FAILED)
            if instance.saga_name == ExecutionSaga.get_name():
                self.logger.info(f"Saga {instance.saga_id} steps done, waiting for execution completion event")
            else:
                await self._complete_saga(instance)

        except Exception as e:
            self.logger.error(f"Error executing saga {instance.saga_id}: {e}", exc_info=True)

            if self.config.enable_compensation:
                await self._compensate_saga(instance, context)
            else:
                await self._fail_saga(instance, str(e))

    async def _compensate_saga(self, instance: Saga, context: SagaContext) -> None:
        """Execute compensation steps"""
        self.logger.info(f"Starting compensation for saga {instance.saga_id}")

        # Only update state if not already cancelled
        if instance.state != SagaState.CANCELLED:
            instance.state = SagaState.COMPENSATING
            await self._save_saga(instance)

        # Execute compensations in reverse order
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

        # Mark saga as failed or keep as cancelled
        if instance.state == SagaState.CANCELLED:
            # Keep cancelled state but update compensated steps
            instance.updated_at = datetime.now(UTC)
            await self._save_saga(instance)
            self.logger.info(f"Saga {instance.saga_id} compensation completed after cancellation")
        else:
            # Mark as failed for non-cancelled compensations
            await self._fail_saga(instance, "Saga compensated due to failure")

    async def _complete_saga(self, instance: Saga) -> None:
        """Mark saga as completed"""
        instance.state = SagaState.COMPLETED
        instance.completed_at = datetime.now(UTC)
        await self._save_saga(instance)

        # Remove from running instances
        self._running_instances.pop(instance.saga_id, None)

        self.logger.info(f"Saga {instance.saga_id} completed successfully")

    async def _fail_saga(self, instance: Saga, error_message: str) -> None:
        """Mark saga as failed"""
        instance.state = SagaState.FAILED
        instance.error_message = error_message
        instance.completed_at = datetime.now(UTC)
        await self._save_saga(instance)

        # Remove from running instances
        self._running_instances.pop(instance.saga_id, None)

        self.logger.error(f"Saga {instance.saga_id} failed: {error_message}")

    async def _check_timeouts(self) -> None:
        """Check for saga timeouts"""
        while self.is_running:
            try:
                # Check every 30 seconds
                await asyncio.sleep(30)

                cutoff_time = datetime.now(UTC) - timedelta(seconds=self.config.timeout_seconds)

                timed_out = await self._repo.find_timed_out_sagas(cutoff_time)

                for instance in timed_out:
                    self.logger.warning(f"Saga {instance.saga_id} timed out")

                    instance.state = SagaState.TIMEOUT
                    instance.error_message = f"Saga timed out after {self.config.timeout_seconds} seconds"
                    instance.completed_at = datetime.now(UTC)

                    await self._save_saga(instance)
                    self._running_instances.pop(instance.saga_id, None)

            except Exception as e:
                self.logger.error(f"Error checking timeouts: {e}")

    async def _save_saga(self, instance: Saga) -> None:
        """Persist saga through repository"""
        instance.updated_at = datetime.now(UTC)
        await self._repo.upsert_saga(instance)

    async def get_saga_status(self, saga_id: str) -> Saga | None:
        """Get saga instance status"""
        # Check memory first
        if saga_id in self._running_instances:
            return self._running_instances[saga_id]

        return await self._repo.get_saga(saga_id)

    async def get_execution_sagas(self, execution_id: str) -> list[Saga]:
        """Get all sagas for an execution, sorted by created_at descending (newest first)"""
        result = await self._repo.get_sagas_by_execution(execution_id)
        return result.sagas

    async def cancel_saga(self, saga_id: str) -> bool:
        """Cancel a running saga and trigger compensation.

        Args:
            saga_id: The ID of the saga to cancel

        Returns:
            True if cancelled successfully, False otherwise
        """
        try:
            # Get saga instance
            saga_instance = await self.get_saga_status(saga_id)
            if not saga_instance:
                self.logger.error("Saga not found", extra={"saga_id": saga_id})
                return False

            # Check if saga can be cancelled
            if saga_instance.state not in [SagaState.RUNNING, SagaState.CREATED]:
                self.logger.warning(
                    "Cannot cancel saga in current state. Only RUNNING or CREATED sagas can be cancelled.",
                    extra={"saga_id": saga_id, "state": saga_instance.state},
                )
                return False

            # Update state to CANCELLED
            saga_instance.state = SagaState.CANCELLED
            saga_instance.error_message = "Saga cancelled by user request"
            saga_instance.completed_at = datetime.now(UTC)

            # Log cancellation with user context if available
            user_id = saga_instance.context_data.get("user_id")
            self.logger.info(
                "Saga cancellation initiated",
                extra={
                    "saga_id": saga_id,
                    "execution_id": saga_instance.execution_id,
                    "user_id": user_id,
                },
            )

            # Save state
            await self._save_saga(saga_instance)

            # Remove from running instances
            self._running_instances.pop(saga_id, None)

            # Publish cancellation event
            if self._producer and self.config.store_events:
                await self._publish_saga_cancelled_event(saga_instance)

            # Trigger compensation if saga was running and has completed steps
            if saga_instance.completed_steps and self.config.enable_compensation:
                # Get saga class
                saga_class = self._sagas.get(saga_instance.saga_name)
                if saga_class:
                    # Create saga instance and context
                    saga = saga_class()
                    try:
                        saga.bind_dependencies(
                            producer=self._producer,
                            alloc_repo=self._alloc_repo,
                            publish_commands=bool(getattr(self.config, "publish_commands", False)),
                        )
                    except Exception:
                        pass
                    context = SagaContext(saga_instance.saga_id, saga_instance.execution_id)

                    # Restore context data
                    for key, value in saga_instance.context_data.items():
                        context.set(key, value)

                    # Get steps and build compensation list
                    steps = saga.get_steps()
                    for step in steps:
                        if step.name in saga_instance.completed_steps:
                            compensation = step.get_compensation()
                            if compensation:
                                context.add_compensation(compensation)

                    # Execute compensation
                    await self._compensate_saga(saga_instance, context)
                else:
                    self.logger.error(
                        "Saga class not found for compensation",
                        extra={"saga_name": saga_instance.saga_name, "saga_id": saga_id},
                    )

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
        """Publish saga cancelled event.

        Args:
            saga_instance: The cancelled saga instance
        """
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
                await self._producer.produce(event_to_produce=event, key=saga_instance.execution_id)

            self.logger.info(f"Published cancellation event for saga {saga_instance.saga_id}")

        except Exception as e:
            self.logger.error(f"Failed to publish saga cancellation event: {e}")


def create_saga_orchestrator(
    saga_repository: SagaRepository,
    producer: UnifiedProducer,
    schema_registry_manager: SchemaRegistryManager,
    settings: Settings,
    event_store: EventStore,
    idempotency_manager: IdempotencyManager,
    resource_allocation_repository: ResourceAllocationRepository,
    config: SagaConfig,
    logger: logging.Logger,
    event_metrics: EventMetrics,
) -> SagaOrchestrator:
    """Factory function to create a saga orchestrator.

    Args:
        saga_repository: Repository for saga persistence
        producer: Kafka producer instance
        schema_registry_manager: Schema registry manager for event serialization
        settings: Application settings
        event_store: Event store instance for event sourcing
        idempotency_manager: Manager for idempotent event processing
        resource_allocation_repository: Repository for resource allocations
        config: Saga configuration
        logger: Logger instance
        event_metrics: Event metrics for tracking Kafka consumption

    Returns:
        A new saga orchestrator instance
    """
    return SagaOrchestrator(
        config,
        saga_repository=saga_repository,
        producer=producer,
        schema_registry_manager=schema_registry_manager,
        settings=settings,
        event_store=event_store,
        idempotency_manager=idempotency_manager,
        resource_allocation_repository=resource_allocation_repository,
        logger=logger,
        event_metrics=event_metrics,
    )
