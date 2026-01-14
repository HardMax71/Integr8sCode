from __future__ import annotations

from collections.abc import Mapping

import redis.asyncio as redis
from pydantic import TypeAdapter
from pymongo.errors import DuplicateKeyError

from app.domain.idempotency import IdempotencyRecord

_record_adapter = TypeAdapter(IdempotencyRecord)


class RedisIdempotencyRepository:
    """Redis-backed repository compatible with IdempotencyManager expectations.

    Key shape: <prefix>:<derived-key>
    Value: JSON document serialized via Pydantic TypeAdapter.
    Expiration: handled by Redis key expiry; initial EX set on insert.
    """

    def __init__(self, client: redis.Redis, key_prefix: str = "idempotency") -> None:
        self._r = client
        self._prefix = key_prefix.rstrip(":")

    def _full_key(self, key: str) -> str:
        return key if key.startswith(f"{self._prefix}:") else f"{self._prefix}:{key}"

    async def find_by_key(self, key: str) -> IdempotencyRecord | None:
        raw = await self._r.get(self._full_key(key))
        return _record_adapter.validate_json(raw) if raw else None

    async def insert_processing(self, record: IdempotencyRecord) -> None:
        ok = await self._r.set(
            self._full_key(record.key),
            _record_adapter.dump_json(record),
            ex=record.ttl_seconds,
            nx=True,
        )
        if not ok:
            raise DuplicateKeyError("Key already exists")

    async def update_record(self, record: IdempotencyRecord) -> int:
        k = self._full_key(record.key)
        pipe = self._r.pipeline()
        pipe.ttl(k)
        pipe.get(k)
        results: list[int | bytes | None] = await pipe.execute()
        ttl_val, raw = results[0], results[1]
        if not raw:
            return 0
        ex = ttl_val if isinstance(ttl_val, int) and ttl_val > 0 else None
        await self._r.set(k, _record_adapter.dump_json(record), ex=ex)
        return 1

    async def delete_key(self, key: str) -> int:
        result = await self._r.delete(self._full_key(key))
        return int(result) if result else 0

    async def aggregate_status_counts(self, key_prefix: str) -> Mapping[str, int]:
        pattern = f"{key_prefix.rstrip(':')}:*"
        counts: dict[str, int] = {}
        async for k in self._r.scan_iter(match=pattern, count=200):
            raw = await self._r.get(k)
            if raw:
                rec = _record_adapter.validate_json(raw)
                counts[rec.status] = counts.get(rec.status, 0) + 1
        return counts

    async def health_check(self) -> None:
        await self._r.ping()  # type: ignore[misc]  # redis-py dual sync/async return type
