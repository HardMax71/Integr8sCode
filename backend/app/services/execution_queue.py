from __future__ import annotations

import time
from typing import Any

import redis.asyncio as redis
import structlog

from app.core.metrics.queue import QueueMetrics
from app.domain.enums import QueuePriority
from app.domain.events import ExecutionRequestedEvent

PRIORITY_SCORES: dict[QueuePriority, int] = {
    QueuePriority.CRITICAL: 0,
    QueuePriority.HIGH: 1,
    QueuePriority.NORMAL: 2,
    QueuePriority.LOW: 3,
    QueuePriority.BACKGROUND: 4,
}

_PENDING_KEY = "exec_queue:pending"
_ACTIVE_KEY = "exec_queue:active"
_EVENT_TTL = 86400  # 24 hours


def _event_key(execution_id: str) -> str:
    return f"exec_queue:event:{execution_id}"


def _score_for(priority: QueuePriority) -> float:
    return PRIORITY_SCORES[priority] * 10**12 + int(time.time() * 1000)


_UPDATE_PRIORITY_LUA = """
local pending_key = KEYS[1]
local exec_id = ARGV[1]
local new_score = tonumber(ARGV[2])

if not redis.call('ZSCORE', pending_key, exec_id) then
    return 0
end

redis.call('ZADD', pending_key, new_score, exec_id)
return 1
"""

_TRY_SCHEDULE_LUA = """
local active_key = KEYS[1]
local pending_key = KEYS[2]
local max_active = tonumber(ARGV[1])

local current = redis.call('SCARD', active_key)
if current >= max_active then
    return nil
end

local result = redis.call('ZPOPMIN', pending_key, 1)
if #result == 0 then
    return nil
end

local exec_id = result[1]
redis.call('SADD', active_key, exec_id)
return exec_id
"""


class ExecutionQueueService:
    """Redis-backed priority queue for execution scheduling."""

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

    async def _get_schedule_script(self) -> Any:
        if self._schedule_script is None:
            self._schedule_script = self._redis.register_script(_TRY_SCHEDULE_LUA)
        return self._schedule_script

    async def _get_update_priority_script(self) -> Any:
        if self._update_priority_script is None:
            self._update_priority_script = self._redis.register_script(_UPDATE_PRIORITY_LUA)
        return self._update_priority_script

    async def enqueue(self, event: ExecutionRequestedEvent) -> int:
        execution_id = event.execution_id
        score = _score_for(event.priority)

        pipe = self._redis.pipeline(transaction=True)
        pipe.zadd(_PENDING_KEY, {execution_id: score})
        pipe.set(_event_key(execution_id), event.model_dump_json(), ex=_EVENT_TTL)
        await pipe.execute()

        rank: int | None = await self._redis.zrank(_PENDING_KEY, execution_id)
        position = rank if rank is not None else 0

        self._metrics.record_enqueue()
        self._logger.info("Enqueued execution", execution_id=execution_id, priority=event.priority, position=position)
        return position

    async def try_schedule(self, max_active: int) -> tuple[str, ExecutionRequestedEvent] | None:
        script = await self._get_schedule_script()
        result = await script(keys=[_ACTIVE_KEY, _PENDING_KEY], args=[max_active])
        if result is None:
            return None

        execution_id = result if isinstance(result, str) else result.decode()
        event_json = await self._redis.get(_event_key(execution_id))
        if event_json is None:
            self._logger.warning("Event data missing for scheduled execution", execution_id=execution_id)
            await self._redis.srem(_ACTIVE_KEY, execution_id)  # type: ignore[misc]
            return None

        event_str = event_json if isinstance(event_json, str) else event_json.decode()
        event = ExecutionRequestedEvent.model_validate_json(event_str)

        self._metrics.record_schedule()
        self._logger.info("Scheduled execution from queue", execution_id=execution_id)
        return execution_id, event

    async def release(self, execution_id: str) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.srem(_ACTIVE_KEY, execution_id)
        pipe.delete(_event_key(execution_id))
        await pipe.execute()
        self._logger.debug("Released execution from active set", execution_id=execution_id)

    async def update_priority(self, execution_id: str, new_priority: QueuePriority) -> bool:
        script = await self._get_update_priority_script()
        new_score = _score_for(new_priority)
        result = await script(keys=[_PENDING_KEY], args=[execution_id, new_score])
        if not result:
            return False
        self._logger.info(
            "Updated execution priority", execution_id=execution_id, new_priority=new_priority,
        )
        return True

    async def remove(self, execution_id: str) -> bool:
        pipe = self._redis.pipeline(transaction=True)
        pipe.zrem(_PENDING_KEY, execution_id)
        pipe.delete(_event_key(execution_id))
        pipe.srem(_ACTIVE_KEY, execution_id)
        results = await pipe.execute()
        removed = bool(results[0]) or bool(results[2])
        if removed:
            self._logger.info("Removed execution from queue", execution_id=execution_id)
        return removed

    async def get_queue_status(self) -> dict[str, int]:
        pipe = self._redis.pipeline(transaction=False)
        pipe.zcard(_PENDING_KEY)
        pipe.scard(_ACTIVE_KEY)
        pending, active = await pipe.execute()
        return {"queue_depth": pending, "active_count": active}

    async def get_pending_by_priority(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for priority, band in PRIORITY_SCORES.items():
            low = band * 10**12
            high = (band + 1) * 10**12 - 1
            count: int = await self._redis.zcount(_PENDING_KEY, low, high)
            if count > 0:
                counts[priority] = count
        return counts
