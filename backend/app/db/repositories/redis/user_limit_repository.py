from __future__ import annotations

import redis.asyncio as redis


class UserLimitRepository:
    """Simple per-user execution counter."""

    KEY = "exec:user_count"

    def __init__(self, redis_client: redis.Redis, max_per_user: int = 100) -> None:
        self._redis = redis_client
        self._max_per_user = max_per_user

    async def try_increment(self, user_id: str) -> bool:
        """Increment user count. Returns True if under limit, False if limit exceeded."""
        count = await self._redis.hincrby(self.KEY, user_id, 1)  # type: ignore[misc]
        if count > self._max_per_user:
            await self._redis.hincrby(self.KEY, user_id, -1)  # type: ignore[misc]
            return False
        return True

    async def decrement(self, user_id: str) -> None:
        """Decrement user count."""
        await self._redis.hincrby(self.KEY, user_id, -1)  # type: ignore[misc]
