from __future__ import annotations

import redis.asyncio as redis


class IdempotencyRepository:
    """Simple idempotency using Redis SET NX.

    Pattern:
    1. try_reserve(key) - returns True if new, False if duplicate
    2. If duplicate and need cached result - get_result(key)
    3. After processing - store_result(key, json)
    """

    KEY_PREFIX = "idempotent"

    def __init__(self, redis_client: redis.Redis, default_ttl: int = 86400) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl

    async def try_reserve(self, key: str, ttl: int | None = None) -> bool:
        """Reserve key atomically. Returns True if new (should process), False if duplicate."""
        full_key = f"{self.KEY_PREFIX}:{key}"
        result = await self._redis.set(full_key, "1", nx=True, ex=ttl or self._default_ttl)
        return result is not None

    async def store_result(self, key: str, result_json: str, ttl: int | None = None) -> None:
        """Store result for duplicate requests to retrieve."""
        full_key = f"{self.KEY_PREFIX}:{key}"
        await self._redis.set(full_key, result_json, ex=ttl or self._default_ttl)

    async def get_result(self, key: str) -> str | None:
        """Get cached result if exists."""
        full_key = f"{self.KEY_PREFIX}:{key}"
        result = await self._redis.get(full_key)
        return str(result) if result is not None else None
