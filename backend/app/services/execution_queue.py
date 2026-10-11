from __future__ import annotations

import time
from typing import Any

import redis.asyncio as redis
import structlog

from app.core.metrics.queue import QueueMetrics
from app.domain.enums import QueuePriority
from app.domain.events import ExecutionRequestedEvent

PRIORITY_ORDER: list[QueuePriority] = [
    QueuePriority.CRITICAL,
    QueuePriority.HIGH,
    QueuePriority.NORMAL,
    QueuePriority.LOW,
    QueuePriority.BACKGROUND,
]

_PENDING_PREFIX = "exec_queue:pending:"
_PENDING_KEYS = [f"{_PENDING_PREFIX}{p}" for p in PRIORITY_ORDER]
# Sorted set of scheduled ids scored by a deadline, so a slot whose release got lost frees itself
_RUNNING_KEY = "exec_queue:running"
_EVENT_TTL = 86400  # 24 hours


def _event_key(execution_id: str) -> str:
    return f"exec_queue:event:{execution_id}"


def _retry_key(execution_id: str) -> str:
    return f"exec_queue:retries:{execution_id}"


def _pending_key(priority: QueuePriority) -> str:
    return f"{_PENDING_PREFIX}{priority}"


def _user_key(user_id: str) -> str:
    return f"exec_queue:user:{user_id}"


def _owner_key(execution_id: str) -> str:
    return f"exec_queue:owner:{execution_id}"


_UPDATE_PRIORITY_LUA = """
local new_key = KEYS[1]
local exec_id = ARGV[1]

for i = 2, #KEYS do
    local score = redis.call('ZSCORE', KEYS[i], exec_id)
    if score then
        redis.call('ZREM', KEYS[i], exec_id)
        redis.call('ZADD', new_key, score, exec_id)
        return 1
    end
end
return 0
"""

_TRY_SCHEDULE_LUA = """
local running_key = KEYS[1]
local max_active = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local deadline = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', running_key, '-inf', now)
if redis.call('ZCARD', running_key) >= max_active then
    return nil
end

for i = 2, #KEYS do
    local result = redis.call('ZPOPMIN', KEYS[i], 1)
    if #result > 0 then
        local exec_id = result[1]
        local enqueue_score = result[2]
        local priority_idx = i - 2
        redis.call('ZADD', running_key, deadline, exec_id)
        return {exec_id, enqueue_score, priority_idx}
    end
end

return nil
"""

_RESERVE_USER_SLOT_LUA = """
local user_key = KEYS[1]
local owner_key = KEYS[2]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local exec_id = ARGV[4]
local user_id = ARGV[5]

redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
if redis.call('ZCARD', user_key) >= limit then
    return 0
end
redis.call('ZADD', user_key, now + ttl, exec_id)
redis.call('EXPIRE', user_key, ttl)
redis.call('SET', owner_key, user_id, 'EX', ttl)
return 1
"""


class ExecutionQueueService:
    """Redis-backed priority queue for execution scheduling.

    Uses one sorted set per priority level (score = epoch timestamp for FIFO
    within each priority). Scheduling pops from the highest-priority non-empty
    set first via an atomic Lua script.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: structlog.stdlib.BoundLogger,
        queue_metrics: QueueMetrics,
    ) -> None:
        self._redis = redis_client
        self._logger = logger
        self._metrics = queue_metrics
        self._schedule_script: Any = None
        self._update_priority_script: Any = None
        self._reserve_user_slot_script: Any = None

    async def _get_schedule_script(self) -> Any:
        if self._schedule_script is None:
            self._schedule_script = self._redis.register_script(_TRY_SCHEDULE_LUA)
        return self._schedule_script

    async def _get_update_priority_script(self) -> Any:
        if self._update_priority_script is None:
            self._update_priority_script = self._redis.register_script(_UPDATE_PRIORITY_LUA)
        return self._update_priority_script

    async def _get_reserve_user_slot_script(self) -> Any:
        if self._reserve_user_slot_script is None:
            self._reserve_user_slot_script = self._redis.register_script(_RESERVE_USER_SLOT_LUA)
        return self._reserve_user_slot_script

    async def reserve_user_slot(self, user_id: str, execution_id: str, limit: int) -> bool:
        """Count an execution against its user's limit; False when the user already has ``limit`` in flight.

        A reservation lasts as long as a queued event does, so one whose release got lost frees itself.
        """
        script = await self._get_reserve_user_slot_script()
        reserved = await script(
            keys=[_user_key(user_id), _owner_key(execution_id)],
            args=[time.time(), limit, _EVENT_TTL, execution_id, user_id],
        )
        return bool(reserved)

    async def release_user_slot(self, execution_id: str) -> None:
        owner = await self._redis.get(_owner_key(execution_id))
        if owner is None:
            return
        user_id = owner if isinstance(owner, str) else owner.decode()
        pipe = self._redis.pipeline(transaction=True)
        pipe.zrem(_user_key(user_id), execution_id)
        pipe.delete(_owner_key(execution_id))
        await pipe.execute()

    async def enqueue(self, event: ExecutionRequestedEvent) -> int:
        execution_id = event.execution_id
        key = _pending_key(event.priority)
        score = time.time()

        pipe = self._redis.pipeline(transaction=True)
        pipe.zadd(key, {execution_id: score})
        pipe.set(_event_key(execution_id), event.model_dump_json(), ex=_EVENT_TTL)
        await pipe.execute()

        rank = await self._redis.zrank(key, execution_id)
        position = rank if isinstance(rank, int) else 0

        self._metrics.record_enqueue()
        self._logger.info("Enqueued execution", execution_id=execution_id, priority=event.priority, position=position)
        return position

    async def try_schedule(self, max_active: int, slot_seconds: int) -> tuple[str, ExecutionRequestedEvent] | None:
        """Move the next pending execution into a running slot that expires after ``slot_seconds``."""
        script = await self._get_schedule_script()
        now = time.time()
        result = await script(keys=[_RUNNING_KEY, *_PENDING_KEYS], args=[max_active, now, now + slot_seconds])
        if result is None:
            return None

        raw_id, raw_score, raw_priority_idx = result
        execution_id = raw_id if isinstance(raw_id, str) else raw_id.decode()
        enqueue_score = float(raw_score)
        priority = PRIORITY_ORDER[int(raw_priority_idx)]

        event_json = await self._redis.get(_event_key(execution_id))
        if event_json is None:
            self._logger.error(
                "Event data expired or missing for scheduled execution, execution lost",
                execution_id=execution_id,
            )
            await self._redis.zrem(_RUNNING_KEY, execution_id)
            self._metrics.record_event_data_lost()
            return None

        event_str = event_json if isinstance(event_json, str) else event_json.decode()
        event = ExecutionRequestedEvent.model_validate_json(event_str)

        wait_seconds = time.time() - enqueue_score
        self._metrics.record_wait_time(wait_seconds, str(priority))
        self._metrics.record_schedule()
        self._logger.info(
            "Scheduled execution from queue", execution_id=execution_id, wait_seconds=round(wait_seconds, 3)
        )
        return execution_id, event

    async def increment_retry_count(self, execution_id: str) -> int:
        """Atomically increment and return the retry count for an execution."""
        key = _retry_key(execution_id)
        count: int = await self._redis.incr(key)
        await self._redis.expire(key, _EVENT_TTL)
        return count

    async def release(self, execution_id: str) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.zrem(_RUNNING_KEY, execution_id)
        pipe.delete(_event_key(execution_id))
        was_active, _ = await pipe.execute()
        if was_active:
            self._metrics.record_release()
        self._logger.debug("Released execution from active set", execution_id=execution_id)

    async def update_priority(self, execution_id: str, new_priority: QueuePriority) -> bool:
        script = await self._get_update_priority_script()
        result = await script(
            keys=[_pending_key(new_priority), *_PENDING_KEYS],
            args=[execution_id],
        )
        if not result:
            return False
        self._logger.info(
            "Updated execution priority",
            execution_id=execution_id,
            new_priority=new_priority,
        )
        return True

    async def remove(self, execution_id: str) -> bool:
        pipe = self._redis.pipeline(transaction=True)
        for key in _PENDING_KEYS:
            pipe.zrem(key, execution_id)
        pipe.delete(_event_key(execution_id))
        pipe.delete(_retry_key(execution_id))
        pipe.zrem(_RUNNING_KEY, execution_id)
        results = await pipe.execute()
        if results[-1]:
            self._metrics.record_release()
        removed = any(results[: len(_PENDING_KEYS)]) or bool(results[-1])
        if removed:
            self._logger.info("Removed execution from queue", execution_id=execution_id)
        return removed

    async def get_queue_status(self) -> dict[str, int]:
        pipe = self._redis.pipeline(transaction=False)
        for key in _PENDING_KEYS:
            pipe.zcard(key)
        pipe.zcount(_RUNNING_KEY, time.time(), "+inf")
        results = await pipe.execute()
        pending = sum(results[: len(_PENDING_KEYS)])
        active = results[-1]
        return {"queue_depth": pending, "active_count": active}

    async def get_pending_by_priority(self) -> dict[str, int]:
        pipe = self._redis.pipeline(transaction=False)
        for key in _PENDING_KEYS:
            pipe.zcard(key)
        results = await pipe.execute()
        counts: dict[str, int] = {}
        for priority, count in zip(PRIORITY_ORDER, results, strict=True):
            if count > 0:
                counts[priority] = count
        return counts
