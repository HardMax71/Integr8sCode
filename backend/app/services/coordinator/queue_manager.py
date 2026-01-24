import asyncio
import heapq
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Tuple

from app.core.metrics import CoordinatorMetrics
from app.domain.events.typed import ExecutionRequestedEvent


class QueuePriority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 5
    LOW = 8
    BACKGROUND = 10


@dataclass(order=True)
class QueuedExecution:
    priority: int
    timestamp: float = field(compare=False)
    event: ExecutionRequestedEvent = field(compare=False)
    retry_count: int = field(default=0, compare=False)

    @property
    def execution_id(self) -> str:
        return self.event.execution_id

    @property
    def user_id(self) -> str:
        return self.event.metadata.user_id or "anonymous"

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp


class QueueManager:
    def __init__(
        self,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
        max_queue_size: int = 10000,
        max_executions_per_user: int = 100,
        stale_timeout_seconds: int = 3600,
    ) -> None:
        self.logger = logger
        self.metrics = coordinator_metrics
        self.max_queue_size = max_queue_size
        self.max_executions_per_user = max_executions_per_user
        self.stale_timeout_seconds = stale_timeout_seconds

        self._queue: List[QueuedExecution] = []
        self._queue_lock = asyncio.Lock()
        self._user_execution_count: Dict[str, int] = defaultdict(int)
        self._execution_users: Dict[str, str] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_executions())
        self.logger.info("Queue manager started")

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        self.logger.info(f"Queue manager stopped. Final queue size: {len(self._queue)}")

    async def add_execution(
        self, event: ExecutionRequestedEvent, priority: QueuePriority | None = None
    ) -> Tuple[bool, int | None, str | None]:
        async with self._queue_lock:
            if len(self._queue) >= self.max_queue_size:
                return False, None, "Queue is full"

            user_id = event.metadata.user_id or "anonymous"

            if self._user_execution_count[user_id] >= self.max_executions_per_user:
                return False, None, f"User execution limit exceeded ({self.max_executions_per_user})"

            if priority is None:
                priority = QueuePriority(event.priority)

            queued = QueuedExecution(priority=priority.value, timestamp=time.time(), event=event)

            heapq.heappush(self._queue, queued)
            self._track_execution(event.execution_id, user_id)
            position = self._get_queue_position(event.execution_id)

            # Update single authoritative metric for execution request queue depth
            self.metrics.update_execution_request_queue_size(len(self._queue))

            self.logger.info(
                f"Added execution {event.execution_id} to queue. "
                f"Priority: {priority.name}, Position: {position}, "
                f"Queue size: {len(self._queue)}"
            )

            return True, position, None

    async def get_next_execution(self) -> ExecutionRequestedEvent | None:
        async with self._queue_lock:
            while self._queue:
                queued = heapq.heappop(self._queue)

                if self._is_stale(queued):
                    self._untrack_execution(queued.execution_id)
                    self._record_removal("stale")
                    continue

                self._untrack_execution(queued.execution_id)
                self._record_wait_time(queued)
                # Update metric after removal from the queue
                self.metrics.update_execution_request_queue_size(len(self._queue))

                self.logger.info(
                    f"Retrieved execution {queued.execution_id} from queue. "
                    f"Wait time: {queued.age_seconds:.2f}s, Queue size: {len(self._queue)}"
                )

                return queued.event

            return None

    async def remove_execution(self, execution_id: str) -> bool:
        async with self._queue_lock:
            initial_size = len(self._queue)
            self._queue = [q for q in self._queue if q.execution_id != execution_id]

            if len(self._queue) < initial_size:
                heapq.heapify(self._queue)
                self._untrack_execution(execution_id)
                # Update metric after explicit removal
                self.metrics.update_execution_request_queue_size(len(self._queue))
                self.logger.info(f"Removed execution {execution_id} from queue")
                return True

            return False

    async def get_queue_position(self, execution_id: str) -> int | None:
        async with self._queue_lock:
            return self._get_queue_position(execution_id)

    async def get_queue_stats(self) -> Dict[str, Any]:
        async with self._queue_lock:
            priority_counts: Dict[str, int] = defaultdict(int)
            user_counts: Dict[str, int] = defaultdict(int)

            for queued in self._queue:
                priority_name = QueuePriority(queued.priority).name
                priority_counts[priority_name] += 1
                user_counts[queued.user_id] += 1

            top_users = dict(sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10])

            return {
                "total_size": len(self._queue),
                "priority_distribution": dict(priority_counts),
                "top_users": top_users,
                "max_queue_size": self.max_queue_size,
                "utilization_percent": (len(self._queue) / self.max_queue_size) * 100,
            }

    async def requeue_execution(
        self, event: ExecutionRequestedEvent, increment_retry: bool = True
    ) -> Tuple[bool, int | None, str | None]:
        def _next_lower(p: QueuePriority) -> QueuePriority:
            order = [
                QueuePriority.CRITICAL,
                QueuePriority.HIGH,
                QueuePriority.NORMAL,
                QueuePriority.LOW,
                QueuePriority.BACKGROUND,
            ]
            try:
                idx = order.index(p)
            except ValueError:
                # Fallback: treat unknown numeric as NORMAL
                idx = order.index(QueuePriority.NORMAL)
            return order[min(idx + 1, len(order) - 1)]

        if increment_retry:
            original_priority = QueuePriority(event.priority)
            new_priority = _next_lower(original_priority)
        else:
            new_priority = QueuePriority(event.priority)

        return await self.add_execution(event, priority=new_priority)

    def _get_queue_position(self, execution_id: str) -> int | None:
        for position, queued in enumerate(self._queue):
            if queued.execution_id == execution_id:
                return position
        return None

    def _is_stale(self, queued: QueuedExecution) -> bool:
        return queued.age_seconds > self.stale_timeout_seconds

    def _track_execution(self, execution_id: str, user_id: str) -> None:
        self._user_execution_count[user_id] += 1
        self._execution_users[execution_id] = user_id

    def _untrack_execution(self, execution_id: str) -> None:
        if execution_id in self._execution_users:
            user_id = self._execution_users.pop(execution_id)
            self._user_execution_count[user_id] -= 1
            if self._user_execution_count[user_id] <= 0:
                del self._user_execution_count[user_id]

    def _record_removal(self, reason: str) -> None:
        # No-op: we keep a single queue depth metric and avoid operation counters
        return

    def _record_wait_time(self, queued: QueuedExecution) -> None:
        self.metrics.record_queue_wait_time_by_priority(
            queued.age_seconds, QueuePriority(queued.priority).name, "default"
        )

    def _update_add_metrics(self, priority: QueuePriority) -> None:
        # Deprecated in favor of single execution queue depth metric
        self.metrics.update_execution_request_queue_size(len(self._queue))

    def _update_queue_size(self) -> None:
        self.metrics.update_execution_request_queue_size(len(self._queue))

    async def _cleanup_stale_executions(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(300)

                async with self._queue_lock:
                    stale_executions = []
                    active_executions = []

                    for queued in self._queue:
                        if self._is_stale(queued):
                            stale_executions.append(queued)
                        else:
                            active_executions.append(queued)

                    if stale_executions:
                        self._queue = active_executions
                        heapq.heapify(self._queue)

                        for queued in stale_executions:
                            self._untrack_execution(queued.execution_id)

                        # Update metric after stale cleanup
                        self.metrics.update_execution_request_queue_size(len(self._queue))
                        self.logger.info(f"Cleaned {len(stale_executions)} stale executions from queue")

            except Exception as e:
                self.logger.error(f"Error in queue cleanup: {e}")
