from __future__ import annotations

from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase


class IdempotencyRepository:
    """Repository for idempotency key persistence.

    Encapsulates all Mongo operations and document mapping to keep
    services free of database concerns.
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "idempotency_keys") -> None:
        self._db = db
        self._collection: AsyncIOMotorCollection = self._db.get_collection(collection_name)

    async def find_by_key(self, key: str) -> dict[str, object] | None:
        return await self._collection.find_one({"key": key})

    async def insert_processing(
        self,
        *,
        key: str,
        event_type: str,
        event_id: str,
        created_at: datetime,
        ttl_seconds: int,
    ) -> None:
        doc = {
            "key": key,
            "status": "processing",
            "event_type": event_type,
            "event_id": event_id,
            "created_at": created_at,
            "ttl_seconds": ttl_seconds,
        }
        await self._collection.insert_one(doc)

    async def update_set(self, key: str, fields: dict[str, object]) -> int:
        """Apply $set update. Returns modified count."""
        res = await self._collection.update_one({"key": key}, {"$set": fields})
        return getattr(res, "modified_count", 0) or 0

    async def delete_key(self, key: str) -> int:
        res = await self._collection.delete_one({"key": key})
        return getattr(res, "deleted_count", 0) or 0

    async def aggregate_status_counts(self, key_prefix: str) -> dict[str, int]:
        pipeline: list[dict[str, object]] = [
            {"$match": {"key": {"$regex": f"^{key_prefix}:"}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        counts: dict[str, int] = {}
        async for doc in self._collection.aggregate(pipeline):
            status = str(doc.get("_id"))
            count = int(doc.get("count", 0))
            counts[status] = count
        return counts

    async def health_check(self) -> None:
        # A lightweight op to verify connectivity/permissions
        await self._collection.find_one({}, {"_id": 1})

