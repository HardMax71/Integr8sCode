"""Execution Coordinator - stateless event handler.

Coordinates execution scheduling across the system. Receives events,
processes them, and publishes results. No lifecycle management.
All state is stored in Redis repositories.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from app.core.metrics import CoordinatorMetrics, EventMetrics
from app.db.repositories import (
    ExecutionQueueRepository,
    ExecutionStateRepository,
    QueuePriority,
    ResourceRepository,
)
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import (
    CreatePodCommandEvent,
    EventMetadata,
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
)
from app.events.core import UnifiedProducer


class ExecutionCoordinator:
    """Stateless execution coordinator - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    All state (active executions, queue, resources) stored in Redis.
    """

    def __init__(
        self,
        producer: UnifiedProducer,
        execution_repository: ExecutionRepository,
        state_repo: ExecutionStateRepository,
        queue_repo: ExecutionQueueRepository,
        resource_repo: ResourceRepository,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
        event_metrics: EventMetrics,
    ) -> None:
        self._producer = producer
        self._execution_repository = execution_repository
        self._state_repo = state_repo
        self._queue_repo = queue_repo
        self._resource_repo = resource_repo
        self._logger = logger
        self._metrics = coordinator_metrics
        self._event_metrics = event_metrics

    async def handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Handle execution requested event - add to queue and try to schedule."""
        self._logger.info(f"Handling ExecutionRequestedEvent: {event.execution_id}")
        start_time = time.time()

        try:
            priority = QueuePriority(event.priority)
            user_id = event.metadata.user_id or "anonymous"

            # Add to Redis queue
            success, position, error = await self._queue_repo.enqueue(
                execution_id=event.execution_id,
                event_data=event.model_dump(mode="json"),
                priority=priority,
                user_id=user_id,
            )

            if not success:
                await self._publish_queue_full(event, error or "Queue is full")
                self._metrics.record_coordinator_execution_scheduled("queue_full")
                return

            # Publish ExecutionAcceptedEvent
            await self._publish_execution_accepted(event, position or 0, event.priority)

            # Track metrics
            duration = time.time() - start_time
            self._metrics.record_coordinator_scheduling_duration(duration)
            self._metrics.record_coordinator_execution_scheduled("queued")

            self._logger.info(f"Execution {event.execution_id} added to queue at position {position}")

            # If at front of queue (position 0), try to schedule immediately
            if position == 0:
                await self._try_schedule_next()

        except Exception as e:
            self._logger.error(f"Failed to handle execution request {event.execution_id}: {e}", exc_info=True)
            self._metrics.record_coordinator_execution_scheduled("error")

    async def handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed - release resources and try to schedule next."""
        execution_id = event.execution_id
        self._logger.info(f"Handling ExecutionCompletedEvent: {execution_id}")

        # Release resources
        await self._resource_repo.release(execution_id)

        # Remove from active state
        await self._state_repo.remove(execution_id)

        # Update metrics
        count = await self._state_repo.get_active_count()
        self._metrics.update_coordinator_active_executions(count)

        self._logger.info(f"Execution {execution_id} completed, resources released")

        # Try to schedule next execution from queue
        await self._try_schedule_next()

    async def handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed - release resources and try to schedule next."""
        execution_id = event.execution_id
        self._logger.info(f"Handling ExecutionFailedEvent: {execution_id}")

        # Release resources
        await self._resource_repo.release(execution_id)

        # Remove from active state
        await self._state_repo.remove(execution_id)

        # Update metrics
        count = await self._state_repo.get_active_count()
        self._metrics.update_coordinator_active_executions(count)

        # Try to schedule next execution from queue
        await self._try_schedule_next()

    async def handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Handle execution cancelled - remove from queue and release resources."""
        execution_id = event.execution_id
        self._logger.info(f"Handling ExecutionCancelledEvent: {execution_id}")

        # Remove from queue if present
        await self._queue_repo.remove(execution_id)

        # Release resources if allocated
        await self._resource_repo.release(execution_id)

        # Remove from active state
        await self._state_repo.remove(execution_id)

        # Update metrics
        count = await self._state_repo.get_active_count()
        self._metrics.update_coordinator_active_executions(count)

    async def _try_schedule_next(self) -> None:
        """Try to schedule the next execution from the queue."""
        result = await self._queue_repo.dequeue()
        if not result:
            return

        execution_id, event_data = result

        # Reconstruct event from stored data
        try:
            event = ExecutionRequestedEvent.model_validate(event_data)
            await self._schedule_execution(event)
        except Exception as e:
            self._logger.error(f"Failed to schedule execution {execution_id}: {e}", exc_info=True)

    async def _schedule_execution(self, event: ExecutionRequestedEvent) -> None:
        """Schedule a single execution - allocate resources and publish command."""
        start_time = time.time()
        execution_id = event.execution_id

        # Try to claim this execution atomically
        claimed = await self._state_repo.try_claim(execution_id)
        if not claimed:
            self._logger.debug(f"Execution {execution_id} already claimed, skipping")
            return

        try:
            # Allocate resources
            allocation = await self._resource_repo.allocate(
                execution_id=execution_id,
                language=event.language,
                requested_cpu=None,
                requested_memory_mb=None,
                requested_gpu=0,
            )

            if not allocation:
                # No resources available, release claim and requeue
                await self._state_repo.remove(execution_id)
                await self._queue_repo.enqueue(
                    execution_id=event.execution_id,
                    event_data=event.model_dump(mode="json"),
                    priority=QueuePriority(event.priority),
                    user_id=event.metadata.user_id or "anonymous",
                )
                self._logger.info(f"No resources available for {execution_id}, requeued")
                return

            # Update metrics
            count = await self._state_repo.get_active_count()
            self._metrics.update_coordinator_active_executions(count)

            # Publish CreatePodCommand
            await self._publish_execution_started(event)

            # Track metrics
            queue_time = start_time - event.timestamp.timestamp()
            priority = QueuePriority(event.priority)
            self._metrics.record_coordinator_queue_time(queue_time, priority.name)

            scheduling_duration = time.time() - start_time
            self._metrics.record_coordinator_scheduling_duration(scheduling_duration)
            self._metrics.record_coordinator_execution_scheduled("scheduled")

            self._logger.info(
                f"Scheduled execution {event.execution_id}. "
                f"Queue time: {queue_time:.2f}s, "
                f"Resources: {allocation.cpu_cores} CPU, {allocation.memory_mb}MB RAM"
            )

        except Exception as e:
            self._logger.error(f"Failed to schedule execution {event.execution_id}: {e}", exc_info=True)

            # Release resources and claim
            await self._resource_repo.release(execution_id)
            await self._state_repo.remove(execution_id)

            count = await self._state_repo.get_active_count()
            self._metrics.update_coordinator_active_executions(count)
            self._metrics.record_coordinator_execution_scheduled("error")

            # Publish failure event
            await self._publish_scheduling_failed(event, str(e))

    async def _build_command_metadata(self, request: ExecutionRequestedEvent) -> EventMetadata:
        """Build metadata for CreatePodCommandEvent with guaranteed user_id."""
        exec_rec = await self._execution_repository.get_execution(request.execution_id)
        user_id: str = exec_rec.user_id if exec_rec and exec_rec.user_id else "system"

        return EventMetadata(
            service_name="execution-coordinator",
            service_version="1.0.0",
            user_id=user_id,
            correlation_id=request.metadata.correlation_id,
        )

    async def _publish_execution_started(self, request: ExecutionRequestedEvent) -> None:
        """Send CreatePodCommandEvent to k8s-worker via SAGA_COMMANDS topic."""
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

        await self._producer.produce(event_to_produce=create_pod_cmd, key=request.execution_id)
        self._logger.info(f"Published CreatePodCommandEvent for {request.execution_id}")

    async def _publish_execution_accepted(
        self, request: ExecutionRequestedEvent, position: int, priority: int
    ) -> None:
        """Publish execution accepted event."""
        event = ExecutionAcceptedEvent(
            execution_id=request.execution_id,
            queue_position=position,
            estimated_wait_seconds=None,
            priority=priority,
            metadata=request.metadata,
        )

        await self._producer.produce(event_to_produce=event)
        self._logger.info(f"ExecutionAcceptedEvent published for {request.execution_id}")

    async def _publish_queue_full(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish queue full event."""
        queue_stats = await self._queue_repo.get_stats()

        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=-1,
            stderr=f"Queue full: {error}. Queue size: {queue_stats.total_size}",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self._producer.produce(event_to_produce=event, key=request.execution_id)

    async def _publish_scheduling_failed(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish scheduling failed event."""
        resource_stats = await self._resource_repo.get_stats()

        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            exit_code=-1,
            stderr=f"Failed to schedule execution: {error}. "
            f"Available resources: CPU={resource_stats.available_cpu}, "
            f"Memory={resource_stats.available_memory_mb}MB",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self._producer.produce(event_to_produce=event, key=request.execution_id)
