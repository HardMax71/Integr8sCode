"""Redis-backed execution queue repository.

Replaces in-memory priority queue (QueueManager) with Redis sorted sets
for stateless, horizontally-scalable services.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from enum import IntEnum

import redis.asyncio as redis


class QueuePriority(IntEnum):
    """Execution queue priorities. Lower value = higher priority."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 5
    LOW = 8
    BACKGROUND = 10


@dataclass
class QueueStats:
    """Queue statistics."""

    total_size: int
    priority_distribution: dict[str, int]
    max_queue_size: int
    utilization_percent: float


class ExecutionQueueRepository:
    """Redis-backed priority queue for executions.

    Uses Redis sorted sets for O(log N) priority queue operations.
    Stores event data in hash maps for retrieval.
    """

    QUEUE_KEY = "exec:queue"
    DATA_KEY_PREFIX = "exec:queue:data"
    USER_COUNT_KEY = "exec:queue:user_count"

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: logging.Logger,
        max_queue_size: int = 10000,
        max_executions_per_user: int = 100,
        stale_timeout_seconds: int = 3600,
    ) -> None:
        self._redis = redis_client
        self._logger = logger
        self.max_queue_size = max_queue_size
        self.max_executions_per_user = max_executions_per_user
        self.stale_timeout_seconds = stale_timeout_seconds

    async def enqueue(
        self,
        execution_id: str,
        event_data: dict[str, object],
        priority: QueuePriority,
        user_id: str,
    ) -> tuple[bool, int | None, str | None]:
        """Add execution to queue. Returns (success, position, error)."""
        # Check queue size
        queue_size = await self._redis.zcard(self.QUEUE_KEY)
        if queue_size >= self.max_queue_size:
            return False, None, "Queue is full"

        # Check user limit
        user_count = await self._redis.hincrby(self.USER_COUNT_KEY, user_id, 0)  # type: ignore[misc]
        if user_count >= self.max_executions_per_user:
            return False, None, f"User execution limit exceeded ({self.max_executions_per_user})"

        # Score: priority * 1e12 + timestamp (lower = higher priority, earlier = higher priority)
        timestamp = time.time()
        score = priority.value * 1e12 + timestamp

        # Use pipeline for atomicity
        pipe = self._redis.pipeline()

        # Add to sorted set
        pipe.zadd(self.QUEUE_KEY, {execution_id: score})

        # Store event data
        data_key = f"{self.DATA_KEY_PREFIX}:{execution_id}"
        event_data["_enqueue_timestamp"] = timestamp
        event_data["_priority"] = priority.value
        event_data["_user_id"] = user_id
        pipe.hset(data_key, mapping={k: json.dumps(v) if not isinstance(v, str) else v for k, v in event_data.items()})
        pipe.expire(data_key, self.stale_timeout_seconds + 60)

        # Increment user count
        pipe.hincrby(self.USER_COUNT_KEY, user_id, 1)

        await pipe.execute()

        # Get position
        position = await self._redis.zrank(self.QUEUE_KEY, execution_id)

        self._logger.info(
            f"Enqueued execution {execution_id}. Priority: {priority.name}, "
            f"Position: {position}, Queue size: {queue_size + 1}"
        )

        return True, position, None

    async def dequeue(self) -> tuple[str, dict[str, object | float | str]] | None:
        """Remove and return highest priority execution. Returns (execution_id, event_data) or None."""
        while True:
            # Pop the lowest score (highest priority)
            result = await self._redis.zpopmin(self.QUEUE_KEY, count=1)
            if not result:
                return None

            execution_id = result[0][0]
            if isinstance(execution_id, bytes):
                execution_id = execution_id.decode()

            # Get event data
            data_key = f"{self.DATA_KEY_PREFIX}:{execution_id}"
            raw_data = await self._redis.hgetall(data_key)  # type: ignore[misc]

            if not raw_data:
                # Data expired or missing, skip this entry
                self._logger.warning(f"Queue entry {execution_id} has no data, skipping")
                continue

            # Parse data
            event_data: dict[str, object | float | str] = {}
            for k, v in raw_data.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                try:
                    event_data[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    event_data[key] = val

            # Check if stale
            enqueue_time_val = event_data.pop("_enqueue_timestamp", 0)
            enqueue_time = float(enqueue_time_val) if isinstance(enqueue_time_val, (int, float, str)) else 0.0
            event_data.pop("_priority", None)
            user_id_val = event_data.pop("_user_id", "anonymous")
            user_id = str(user_id_val)

            age = time.time() - enqueue_time
            if age > self.stale_timeout_seconds:
                # Stale, clean up and continue
                await self._redis.delete(data_key)
                await self._redis.hincrby(self.USER_COUNT_KEY, user_id, -1)  # type: ignore[misc]
                self._logger.info(f"Skipped stale execution {execution_id} (age: {age:.2f}s)")
                continue

            # Clean up
            await self._redis.delete(data_key)
            await self._redis.hincrby(self.USER_COUNT_KEY, user_id, -1)  # type: ignore[misc]

            self._logger.info(f"Dequeued execution {execution_id}. Wait time: {age:.2f}s")
            return execution_id, event_data

    async def remove(self, execution_id: str) -> bool:
        """Remove specific execution from queue. Returns True if removed."""
        # Get user_id before removing
        data_key = f"{self.DATA_KEY_PREFIX}:{execution_id}"
        raw_data = await self._redis.hgetall(data_key)  # type: ignore[misc]

        removed = await self._redis.zrem(self.QUEUE_KEY, execution_id)
        if removed:
            # Decrement user count
            if raw_data:
                user_id_raw = raw_data.get(b"_user_id") or raw_data.get("_user_id")
                if user_id_raw:
                    user_id = user_id_raw.decode() if isinstance(user_id_raw, bytes) else user_id_raw
                    try:
                        user_id = json.loads(user_id)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    await self._redis.hincrby(self.USER_COUNT_KEY, str(user_id), -1)  # type: ignore[misc]

            await self._redis.delete(data_key)
            self._logger.info(f"Removed execution {execution_id} from queue")
            return True
        return False

    async def get_position(self, execution_id: str) -> int | None:
        """Get queue position of execution (0-indexed)."""
        result = await self._redis.zrank(self.QUEUE_KEY, execution_id)
        return int(result) if result is not None else None

    async def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        total_size = await self._redis.zcard(self.QUEUE_KEY)

        # Count by priority (sample first 1000)
        priority_counts: dict[str, int] = {}
        entries = await self._redis.zrange(self.QUEUE_KEY, 0, 999, withscores=True)
        for _, score in entries:
            priority_value = int(score // 1e12)
            try:
                priority_name = QueuePriority(priority_value).name
            except ValueError:
                priority_name = "UNKNOWN"
            priority_counts[priority_name] = priority_counts.get(priority_name, 0) + 1

        return QueueStats(
            total_size=total_size,
            priority_distribution=priority_counts,
            max_queue_size=self.max_queue_size,
            utilization_percent=(total_size / self.max_queue_size) * 100 if self.max_queue_size > 0 else 0,
        )

    async def cleanup_stale(self) -> int:
        """Remove stale entries. Returns count removed. Call periodically."""
        removed = 0
        threshold_score = QueuePriority.BACKGROUND.value * 1e12 + (time.time() - self.stale_timeout_seconds)

        # Get entries older than threshold
        stale_entries = await self._redis.zrangebyscore(self.QUEUE_KEY, "-inf", threshold_score, start=0, num=100)

        for entry in stale_entries:
            execution_id = entry.decode() if isinstance(entry, bytes) else entry
            if await self.remove(execution_id):
                removed += 1

        if removed:
            self._logger.info(f"Cleaned {removed} stale executions from queue")

        return removed
