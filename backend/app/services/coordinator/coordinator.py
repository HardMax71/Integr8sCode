import asyncio
import heapq
import logging
import time
from collections import defaultdict
from uuid import uuid4

from app.core.metrics import CoordinatorMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.execution import QueuePriority
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


class QueueRejectError(Exception):
    """Raised when an execution cannot be added to the queue."""


_PRIORITY_SORT = {p: i for i, p in enumerate(QueuePriority)}


class ExecutionCoordinator:
    """
    Coordinates execution scheduling across the system.

    This service:
    1. Consumes ExecutionRequested events
    2. Manages execution queue with priority
    3. Enforces per-user rate limits
    4. Publishes CreatePodCommand events for workers
    """

    def __init__(
        self,
        producer: UnifiedProducer,
        execution_repository: ExecutionRepository,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
        max_queue_size: int = 10000,
        max_executions_per_user: int = 100,
        stale_timeout_seconds: int = 3600,
    ) -> None:
        self.logger = logger
        self.metrics = coordinator_metrics
        self.producer = producer
        self.execution_repository = execution_repository

        # Queue configuration
        self._max_queue_size = max_queue_size
        self._max_per_user = max_executions_per_user
        self._stale_timeout = stale_timeout_seconds

        # Queue state – heap of (priority_index, sequence, enqueued_at, event) tuples
        self._queue: list[tuple[int, int, float, ExecutionRequestedEvent]] = []
        self._enqueue_counter = 0
        self._queue_lock = asyncio.Lock()
        self._user_counts: dict[str, int] = defaultdict(int)
        self._execution_users: dict[str, str] = {}

        # Scheduling state
        self._active_executions: set[str] = set()

    async def handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Handle execution requested event - add to queue for processing."""
        self.logger.info(f"HANDLER CALLED: handle_execution_requested for event {event.event_id}")
        start_time = time.time()

        try:
            position = await self._add_to_queue(event)
        except QueueRejectError as e:
            await self._publish_queue_full(event, str(e))
            self.metrics.record_coordinator_execution_scheduled("queue_full")
            return
        except Exception as e:
            self.logger.error(f"Failed to handle execution request {event.execution_id}: {e}", exc_info=True)
            self.metrics.record_coordinator_execution_scheduled("error")
            return

        await self._publish_execution_accepted(event, position)

        duration = time.time() - start_time
        self.metrics.record_coordinator_scheduling_duration(duration)
        self.metrics.record_coordinator_execution_scheduled("queued")

        self.logger.info(f"Execution {event.execution_id} added to queue at position {position}")

        if position == 0:
            await self._try_schedule_next()

    async def handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Handle execution cancelled event."""
        execution_id = event.execution_id

        removed = await self._remove_from_queue(execution_id)
        self._active_executions.discard(execution_id)
        self._untrack_user(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        if removed:
            self.logger.info(f"Execution {execution_id} cancelled and removed from queue")

        await self._try_schedule_next()

    async def handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event."""
        execution_id = event.execution_id

        self._active_executions.discard(execution_id)
        self._untrack_user(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        self.logger.info(f"Execution {execution_id} completed")
        await self._try_schedule_next()

    async def handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event."""
        execution_id = event.execution_id

        self._active_executions.discard(execution_id)
        self._untrack_user(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        await self._try_schedule_next()

    async def _try_schedule_next(self) -> None:
        """Pop the next queued execution and schedule it."""
        execution = await self._pop_next()
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
            await self._publish_create_pod_command(event)

            scheduling_duration = time.time() - start_time
            self.metrics.record_coordinator_scheduling_duration(scheduling_duration)
            self.metrics.record_coordinator_execution_scheduled("scheduled")

            self.logger.info(f"Scheduled execution {event.execution_id}")

        except Exception as e:
            self.logger.error(f"Failed to schedule execution {event.execution_id}: {e}", exc_info=True)

            self._active_executions.discard(event.execution_id)
            self._untrack_user(event.execution_id)
            self.metrics.update_coordinator_active_executions(len(self._active_executions))
            self.metrics.record_coordinator_execution_scheduled("error")

            await self._publish_scheduling_failed(event, str(e))

    async def _add_to_queue(self, event: ExecutionRequestedEvent) -> int:
        """Add execution to queue. Returns queue position. Raises QueueRejectError on failure."""
        async with self._queue_lock:
            if len(self._queue) >= self._max_queue_size:
                self._sweep_stale()
                if len(self._queue) >= self._max_queue_size:
                    raise QueueRejectError("Queue is full")

            user_id = event.metadata.user_id or "anonymous"

            if self._user_counts[user_id] >= self._max_per_user:
                raise QueueRejectError(f"User execution limit exceeded ({self._max_per_user})")

            self._enqueue_counter += 1
            heapq.heappush(self._queue, (_PRIORITY_SORT[event.priority], self._enqueue_counter, time.time(), event))
            self._track_user(event.execution_id, user_id)
            position = self._find_position(event.execution_id) or 0

            self.metrics.update_execution_request_queue_size(len(self._queue))

            self.logger.info(
                f"Added execution {event.execution_id} to queue. "
                f"Priority: {event.priority}, Position: {position}, "
                f"Queue size: {len(self._queue)}"
            )

            return position

    async def _pop_next(self) -> ExecutionRequestedEvent | None:
        """Pop the highest-priority non-stale execution from the queue."""
        async with self._queue_lock:
            while self._queue:
                _, _, enqueued_at, event = heapq.heappop(self._queue)
                age = time.time() - enqueued_at

                if age > self._stale_timeout:
                    self._untrack_user(event.execution_id)
                    continue

                self.metrics.record_coordinator_queue_time(age, event.priority)
                self.metrics.update_execution_request_queue_size(len(self._queue))

                self.logger.info(
                    f"Retrieved execution {event.execution_id} from queue. "
                    f"Wait time: {age:.2f}s, Queue size: {len(self._queue)}"
                )

                return event

            return None

    async def _remove_from_queue(self, execution_id: str) -> bool:
        """Remove a specific execution from the queue (e.g. on cancellation)."""
        async with self._queue_lock:
            initial_size = len(self._queue)
            self._queue = [(p, s, t, e) for p, s, t, e in self._queue if e.execution_id != execution_id]

            if len(self._queue) < initial_size:
                heapq.heapify(self._queue)
                self._untrack_user(execution_id)
                self.metrics.update_execution_request_queue_size(len(self._queue))
                self.logger.info(f"Removed execution {execution_id} from queue")
                return True

            return False

    def _find_position(self, execution_id: str) -> int | None:
        for position, (_, _, _, event) in enumerate(self._queue):
            if event.execution_id == execution_id:
                return position
        return None

    def _track_user(self, execution_id: str, user_id: str) -> None:
        self._user_counts[user_id] += 1
        self._execution_users[execution_id] = user_id

    def _untrack_user(self, execution_id: str) -> None:
        if execution_id in self._execution_users:
            user_id = self._execution_users.pop(execution_id)
            self._user_counts[user_id] -= 1
            if self._user_counts[user_id] <= 0:
                del self._user_counts[user_id]

    def _sweep_stale(self) -> None:
        """Remove stale executions from queue. Must be called under _queue_lock."""
        active: list[tuple[int, int, float, ExecutionRequestedEvent]] = []
        removed = 0
        now = time.time()
        for entry in self._queue:
            if now - entry[2] > self._stale_timeout:
                self._untrack_user(entry[3].execution_id)
                removed += 1
            else:
                active.append(entry)
        if removed:
            self._queue = active
            heapq.heapify(self._queue)
            self.metrics.update_execution_request_queue_size(len(self._queue))
            self.logger.info(f"Swept {removed} stale executions from queue")

    async def _build_command_metadata(self, request: ExecutionRequestedEvent) -> EventMetadata:
        """Build metadata for CreatePodCommandEvent with guaranteed user_id."""
        exec_rec = await self.execution_repository.get_execution(request.execution_id)
        user_id: str = exec_rec.user_id if exec_rec and exec_rec.user_id else "system"

        return EventMetadata(
            service_name="execution-coordinator",
            service_version="1.0.0",
            user_id=user_id,
            correlation_id=request.metadata.correlation_id,
        )

    async def _publish_create_pod_command(self, request: ExecutionRequestedEvent) -> None:
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

        await self.producer.produce(event_to_produce=create_pod_cmd, key=request.execution_id)

    async def _publish_execution_accepted(self, request: ExecutionRequestedEvent, position: int) -> None:
        """Publish execution accepted event to notify that request was valid and queued."""
        self.logger.info(f"Publishing ExecutionAcceptedEvent for execution {request.execution_id}")

        event = ExecutionAcceptedEvent(
            execution_id=request.execution_id,
            queue_position=position,
            estimated_wait_seconds=None,
            priority=request.priority,
            metadata=request.metadata,
        )

        await self.producer.produce(event_to_produce=event, key=request.execution_id)

    async def _publish_queue_full(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish queue full event."""
        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=-1,
            stderr=f"Queue full: {error}. Queue size: {len(self._queue)}",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self.producer.produce(event_to_produce=event, key=request.execution_id)

    async def _publish_scheduling_failed(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish scheduling failed event."""
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
