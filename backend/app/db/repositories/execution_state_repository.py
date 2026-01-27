"""Redis-backed execution state tracking repository.

Replaces in-memory state tracking (_active_executions sets) with Redis
for stateless, horizontally-scalable services.
"""

from __future__ import annotations

import logging

import redis.asyncio as redis


class ExecutionStateRepository:
    """Redis-backed execution state tracking.

    Provides atomic claim/release operations for executions,
    replacing in-memory sets like `_active_executions`.
    """

    KEY_PREFIX = "exec:active"

    def __init__(self, redis_client: redis.Redis, logger: logging.Logger) -> None:
        self._redis = redis_client
        self._logger = logger

    async def try_claim(self, execution_id: str, ttl_seconds: int = 3600) -> bool:
        """Atomically claim an execution. Returns True if claimed, False if already claimed.

        Uses Redis SETNX for atomic check-and-set.
        TTL ensures cleanup if service crashes without releasing.
        """
        key = f"{self.KEY_PREFIX}:{execution_id}"
        result = await self._redis.set(key, "1", nx=True, ex=ttl_seconds)
        if result:
            self._logger.debug(f"Claimed execution {execution_id}")
        return result is not None

    async def is_active(self, execution_id: str) -> bool:
        """Check if an execution is currently active/claimed."""
        key = f"{self.KEY_PREFIX}:{execution_id}"
        result = await self._redis.exists(key)
        return bool(result)

    async def remove(self, execution_id: str) -> bool:
        """Release/remove an execution claim. Returns True if was claimed."""
        key = f"{self.KEY_PREFIX}:{execution_id}"
        deleted = await self._redis.delete(key)
        if deleted:
            self._logger.debug(f"Released execution {execution_id}")
        return bool(deleted > 0)

    async def get_active_count(self) -> int:
        """Get count of active executions. For metrics only."""
        pattern = f"{self.KEY_PREFIX}:*"
        count = 0
        async for _ in self._redis.scan_iter(match=pattern, count=100):
            count += 1
        return count

    async def extend_ttl(self, execution_id: str, ttl_seconds: int = 3600) -> bool:
        """Extend the TTL of an active execution. Returns True if extended."""
        key = f"{self.KEY_PREFIX}:{execution_id}"
        result = await self._redis.expire(key, ttl_seconds)
        return bool(result)
