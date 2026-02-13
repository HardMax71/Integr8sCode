from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from pymongo.errors import DuplicateKeyError

from app.domain.enums import EventType
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _json_default(obj: Any) -> str:
    if isinstance(obj, datetime):
        return _iso(obj)
    return str(obj)


def _parse_iso_datetime(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


class RedisIdempotencyRepository:
    """Redis-backed repository compatible with IdempotencyManager expectations.

    Key shape: <prefix>:<derived-key>
    Value: JSON document with fields similar to Mongo version.
    Expiration: handled by Redis key expiry; initial EX set on insert.
    """

    def __init__(self, client: redis.Redis, key_prefix: str = "idempotency") -> None:
        self._r = client
        self._prefix = key_prefix.rstrip(":")

    def _full_key(self, key: str) -> str:
        # If caller already namespaces, respect it; otherwise prefix.
        return key if key.startswith(f"{self._prefix}:") else f"{self._prefix}:{key}"

    def _doc_to_record(self, doc: dict[str, Any]) -> IdempotencyRecord:
        created_at = doc.get("created_at")
        if isinstance(created_at, str):
            created_at = _parse_iso_datetime(created_at)
        completed_at = doc.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = _parse_iso_datetime(completed_at)
        return IdempotencyRecord(
            key=str(doc.get("key", "")),
            status=IdempotencyStatus(doc.get("status", IdempotencyStatus.PROCESSING)),
            event_type=EventType(doc.get("event_type", "")),
            event_id=str(doc.get("event_id", "")),
            created_at=created_at,  # type: ignore[arg-type]
            ttl_seconds=int(doc.get("ttl_seconds", 0) or 0),
            completed_at=completed_at,
            processing_duration_ms=doc.get("processing_duration_ms"),
            error=doc.get("error"),
            result_json=doc.get("result"),
        )

    def _record_to_doc(self, rec: IdempotencyRecord) -> dict[str, Any]:
        return {
            "key": rec.key,
            "status": rec.status,
            "event_type": rec.event_type,
            "event_id": rec.event_id,
            "created_at": _iso(rec.created_at),
            "ttl_seconds": rec.ttl_seconds,
            "completed_at": _iso(rec.completed_at) if rec.completed_at else None,
            "processing_duration_ms": rec.processing_duration_ms,
            "error": rec.error,
            "result": rec.result_json,
        }

    async def find_by_key(self, key: str) -> IdempotencyRecord | None:
        k = self._full_key(key)
        raw = await self._r.get(k)
        if not raw:
            return None
        try:
            doc: dict[str, Any] = json.loads(raw)
        except Exception:
            return None
        return self._doc_to_record(doc)

    async def insert_processing(self, record: IdempotencyRecord) -> None:
        k = self._full_key(record.key)
        doc = self._record_to_doc(record)
        # SET NX with EX for atomic reservation
        ok = await self._r.set(k, json.dumps(doc, default=_json_default), ex=record.ttl_seconds, nx=True)
        if not ok:
            # Mirror Mongo behavior so manager's DuplicateKeyError path is reused
            raise DuplicateKeyError("Key already exists")

    async def update_record(self, record: IdempotencyRecord) -> int:
        k = self._full_key(record.key)
        # Read-modify-write while preserving TTL
        pipe = self._r.pipeline()
        pipe.ttl(k)
        pipe.get(k)
        ttl_val, raw = await pipe.execute()
        if not raw:
            return 0
        doc = self._record_to_doc(record)
        # Write back, keep TTL if positive
        payload = json.dumps(doc, default=_json_default)
        if isinstance(ttl_val, int) and ttl_val > 0:
            await self._r.set(k, payload, ex=ttl_val)
        else:
            await self._r.set(k, payload)
        return 1

