import logging
import time
from uuid import uuid4

from app.core.metrics import CoordinatorMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import (
    CreatePodCommandEvent,
    DomainEvent,
    EventMetadata,
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
)
from app.events.core import EventDispatcher, UnifiedProducer
from app.services.coordinator.queue_manager import QueueManager, QueuePriority


class ExecutionCoordinator:
    """
    Coordinates execution scheduling across the system.

    This service:
    1. Consumes ExecutionRequested events
    2. Manages execution queue with priority
    3. Enforces rate limits
    4. Publishes CreatePodCommand events for workers
    """

    def __init__(
        self,
        producer: UnifiedProducer,
        dispatcher: EventDispatcher,
        queue_manager: QueueManager,
        execution_repository: ExecutionRepository,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
    ) -> None:
        self.logger = logger
        self.metrics = coordinator_metrics
        self.producer = producer
        self.queue_manager = queue_manager
        self.execution_repository = execution_repository

        self._active_executions: set[str] = set()

        self._register_handlers(dispatcher)

    def _register_handlers(self, dispatcher: EventDispatcher) -> None:
        """Register event handlers on the dispatcher."""
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, self._handle_requested_wrapper)
        dispatcher.register_handler(EventType.EXECUTION_COMPLETED, self._handle_completed_wrapper)
        dispatcher.register_handler(EventType.EXECUTION_FAILED, self._handle_failed_wrapper)
        dispatcher.register_handler(EventType.EXECUTION_CANCELLED, self._handle_cancelled_wrapper)

    async def _handle_requested_wrapper(self, event: DomainEvent) -> None:
        assert isinstance(event, ExecutionRequestedEvent)
        await self._handle_execution_requested(event)

    async def _handle_completed_wrapper(self, event: DomainEvent) -> None:
        assert isinstance(event, ExecutionCompletedEvent)
        await self._handle_execution_completed(event)

    async def _handle_failed_wrapper(self, event: DomainEvent) -> None:
        assert isinstance(event, ExecutionFailedEvent)
        await self._handle_execution_failed(event)

    async def _handle_cancelled_wrapper(self, event: DomainEvent) -> None:
        assert isinstance(event, ExecutionCancelledEvent)
        await self._handle_execution_cancelled(event)

    async def _handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Handle execution requested event - add to queue for processing"""
        self.logger.info(f"HANDLER CALLED: _handle_execution_requested for event {event.event_id}")
        start_time = time.time()

        try:
            # Add to queue with priority
            success, position, error = await self.queue_manager.add_execution(
                event,
                priority=QueuePriority(event.priority),
            )

            if not success:
                # Publish queue full event
                await self._publish_queue_full(event, error or "Queue is full")
                self.metrics.record_coordinator_execution_scheduled("queue_full")
                return

            # Publish ExecutionAcceptedEvent
            if position is None:
                position = 0
            await self._publish_execution_accepted(event, position, event.priority)

            # Track metrics
            duration = time.time() - start_time
            self.metrics.record_coordinator_scheduling_duration(duration)
            self.metrics.record_coordinator_execution_scheduled("queued")

            self.logger.info(f"Execution {event.execution_id} added to queue at position {position}")

            if position == 0:
                await self._try_schedule_next()

        except Exception as e:
            self.logger.error(f"Failed to handle execution request {event.execution_id}: {e}", exc_info=True)
            self.metrics.record_coordinator_execution_scheduled("error")

    async def _handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Handle execution cancelled event"""
        execution_id = event.execution_id

        removed = await self.queue_manager.remove_execution(execution_id)
        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        if removed:
            self.logger.info(f"Execution {execution_id} cancelled and removed from queue")

        await self._try_schedule_next()

    async def _handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event"""
        execution_id = event.execution_id

        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        self.logger.info(f"Execution {execution_id} completed")
        await self._try_schedule_next()

    async def _handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event"""
        execution_id = event.execution_id

        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        await self._try_schedule_next()

    async def _try_schedule_next(self) -> None:
        """Pop the next queued execution and schedule it."""
        execution = await self.queue_manager.get_next_execution()
        if execution:
            await self._schedule_execution(execution)

    async def _schedule_execution(self, event: ExecutionRequestedEvent) -> None:
        """Schedule a single execution."""
        start_time = time.time()
        execution_id = event.execution_id

        if execution_id in self._active_executions:
            self.logger.debug(f"Execution {execution_id} already claimed, skipping")
            return
        self._active_executions.add(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        try:
            await self._publish_execution_started(event)

            # Track metrics
            queue_time = start_time - event.timestamp.timestamp()
            priority = getattr(event, "priority", QueuePriority.NORMAL.value)
            self.metrics.record_coordinator_queue_time(queue_time, QueuePriority(priority).name)

            scheduling_duration = time.time() - start_time
            self.metrics.record_coordinator_scheduling_duration(scheduling_duration)
            self.metrics.record_coordinator_execution_scheduled("scheduled")

            self.logger.info(
                f"Scheduled execution {event.execution_id}. "
                f"Queue time: {queue_time:.2f}s"
            )

        except Exception as e:
            self.logger.error(f"Failed to schedule execution {event.execution_id}: {e}", exc_info=True)

            self._active_executions.discard(event.execution_id)
            self.metrics.update_coordinator_active_executions(len(self._active_executions))
            self.metrics.record_coordinator_execution_scheduled("error")

            await self._publish_scheduling_failed(event, str(e))

    async def _build_command_metadata(self, request: ExecutionRequestedEvent) -> EventMetadata:
        """Build metadata for CreatePodCommandEvent with guaranteed user_id."""
        # Prefer execution record user_id to avoid missing attribution
        exec_rec = await self.execution_repository.get_execution(request.execution_id)
        user_id: str = exec_rec.user_id if exec_rec and exec_rec.user_id else "system"

        return EventMetadata(
            service_name="execution-coordinator",
            service_version="1.0.0",
            user_id=user_id,
            correlation_id=request.metadata.correlation_id,
        )

    async def _publish_execution_started(self, request: ExecutionRequestedEvent) -> None:
        """Send CreatePodCommandEvent to k8s-worker via SAGA_COMMANDS topic"""
        metadata = await self._build_command_metadata(request)

        create_pod_cmd = CreatePodCommandEvent(
            saga_id=str(uuid4()),
            execution_id=request.execution_id,
            script=request.script,
            language=request.language,
            language_version=request.language_version,
            runtime_image=request.runtime_image,
            runtime_command=request.runtime_command,
            runtime_filename=request.runtime_filename,
            timeout_seconds=request.timeout_seconds,
            cpu_limit=request.cpu_limit,
            memory_limit=request.memory_limit,
            cpu_request=request.cpu_request,
            memory_request=request.memory_request,
            priority=request.priority,
            metadata=metadata,
        )

        await self.producer.produce(event_to_produce=create_pod_cmd, key=request.execution_id)

    async def _publish_execution_accepted(self, request: ExecutionRequestedEvent, position: int, priority: int) -> None:
        """Publish execution accepted event to notify that request was valid and queued"""
        self.logger.info(f"Publishing ExecutionAcceptedEvent for execution {request.execution_id}")

        event = ExecutionAcceptedEvent(
            execution_id=request.execution_id,
            queue_position=position,
            estimated_wait_seconds=None,  # Could calculate based on queue analysis
            priority=priority,
            metadata=request.metadata,
        )

        await self.producer.produce(event_to_produce=event)

    async def _publish_queue_full(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish queue full event"""
        # Get queue stats for context
        queue_stats = await self.queue_manager.get_queue_stats()

        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=-1,
            stderr=f"Queue full: {error}. Queue size: {queue_stats.get('total_size', 'unknown')}",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self.producer.produce(event_to_produce=event, key=request.execution_id)

    async def _publish_scheduling_failed(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish scheduling failed event"""
        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            exit_code=-1,
            stderr=f"Failed to schedule execution: {error}",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self.producer.produce(event_to_produce=event, key=request.execution_id)

