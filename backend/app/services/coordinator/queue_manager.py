import asyncio
import heapq
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import logger
from app.core.metrics import Counter, Gauge, Histogram
from app.schemas_avro.event_schemas import ExecutionRequestedEvent


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
            max_queue_size: int = 10000,
            max_executions_per_user: int = 100,
            stale_timeout_seconds: int = 3600,
    ) -> None:
        self.max_queue_size = max_queue_size
        self.max_executions_per_user = max_executions_per_user
        self.stale_timeout_seconds = stale_timeout_seconds

        self._queue: List[QueuedExecution] = []
        self._queue_lock = asyncio.Lock()
        self._user_execution_count: Dict[str, int] = defaultdict(int)
        self._execution_users: Dict[str, str] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        self._init_metrics()

    def _init_metrics(self) -> None:
        self.queue_size = Gauge(
            "execution_queue_size",
            "Current size of execution queue",
            ["queue_name"]
        )
        self.queue_added = Counter(
            "execution_queue_added_total",
            "Total executions added to queue",
            ["priority", "queue_name"]
        )
        self.queue_removed = Counter(
            "execution_queue_removed_total",
            "Total executions removed from queue",
            ["reason", "queue_name"]
        )
        self.queue_wait_time = Histogram(
            "execution_queue_wait_seconds",
            "Time spent waiting in queue",
            ["priority", "queue_name"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0]
        )

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_executions())
        logger.info("Queue manager started")

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

        logger.info(f"Queue manager stopped. Final queue size: {len(self._queue)}")

    async def add_execution(
            self,
            event: ExecutionRequestedEvent,
            priority: Optional[QueuePriority] = None
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        async with self._queue_lock:
            if len(self._queue) >= self.max_queue_size:
                self._record_removal("queue_full")
                return False, None, "Queue is full"

            user_id = event.metadata.user_id or "anonymous"

            if self._user_execution_count[user_id] >= self.max_executions_per_user:
                self._record_removal("user_limit_exceeded")
                return False, None, f"User execution limit exceeded ({self.max_executions_per_user})"

            if priority is None:
                priority = QueuePriority(event.priority)

            queued = QueuedExecution(
                priority=priority.value,
                timestamp=time.time(),
                event=event
            )

            heapq.heappush(self._queue, queued)
            self._track_execution(event.execution_id, user_id)
            position = self._get_queue_position(event.execution_id)

            self._update_add_metrics(priority)

            logger.info(
                f"Added execution {event.execution_id} to queue. "
                f"Priority: {priority.name}, Position: {position}, "
                f"Queue size: {len(self._queue)}"
            )

            return True, position, None

    async def get_next_execution(self) -> Optional[ExecutionRequestedEvent]:
        async with self._queue_lock:
            while self._queue:
                queued = heapq.heappop(self._queue)

                if self._is_stale(queued):
                    self._untrack_execution(queued.execution_id)
                    self._record_removal("stale")
                    continue

                self._untrack_execution(queued.execution_id)
                self._record_wait_time(queued)
                self._record_removal("processed")

                logger.info(
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
                self._record_removal("cancelled")
                self._update_queue_size()
                logger.info(f"Removed execution {execution_id} from queue")
                return True

            return False

    async def get_queue_position(self, execution_id: str) -> Optional[int]:
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

            top_users = dict(sorted(
                user_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10])

            return {
                "total_size": len(self._queue),
                "priority_distribution": dict(priority_counts),
                "top_users": top_users,
                "max_queue_size": self.max_queue_size,
                "utilization_percent": (len(self._queue) / self.max_queue_size) * 100
            }

    async def requeue_execution(
            self,
            event: ExecutionRequestedEvent,
            increment_retry: bool = True
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        if increment_retry:
            original_priority = QueuePriority(event.priority)
            new_priority_value = min(
                original_priority.value + 1,
                QueuePriority.LOW.value
            )
            new_priority = QueuePriority(new_priority_value)
        else:
            new_priority = QueuePriority(event.priority)

        return await self.add_execution(event, priority=new_priority)

    def _get_queue_position(self, execution_id: str) -> Optional[int]:
        for position, queued in enumerate(self._queue, 1):
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
        self.queue_removed.labels(
            reason=reason,
            queue_name="default"
        ).inc()

    def _record_wait_time(self, queued: QueuedExecution) -> None:
        self.queue_wait_time.labels(
            priority=QueuePriority(queued.priority).name,
            queue_name="default"
        ).observe(queued.age_seconds)

    def _update_add_metrics(self, priority: QueuePriority) -> None:
        self.queue_size.labels(queue_name="default").set(len(self._queue))
        self.queue_added.labels(
            priority=priority.name,
            queue_name="default"
        ).inc()

    def _update_queue_size(self) -> None:
        self.queue_size.labels(queue_name="default").set(len(self._queue))

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
                            self._record_removal("stale")

                        self._update_queue_size()
                        logger.info(f"Cleaned {len(stale_executions)} stale executions from queue")

            except Exception as e:
                logger.error(f"Error in queue cleanup: {e}")
