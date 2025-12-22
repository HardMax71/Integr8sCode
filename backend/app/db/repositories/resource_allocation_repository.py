from datetime import datetime, timezone

from app.core.database_context import Collection, Database
from app.domain.events.event_models import CollectionNames


class ResourceAllocationRepository:
    """Repository for resource allocation bookkeeping used by saga steps."""

    def __init__(self, database: Database):
        self._db = database
        self._collection: Collection = self._db.get_collection(CollectionNames.RESOURCE_ALLOCATIONS)

    async def count_active(self, language: str) -> int:
        return await self._collection.count_documents({
            "status": "active",
            "language": language,
        })

    async def create_allocation(
            self,
            allocation_id: str,
            *,
            execution_id: str,
            language: str,
            cpu_request: str,
            memory_request: str,
            cpu_limit: str,
            memory_limit: str,
    ) -> bool:
        doc = {
            "_id": allocation_id,
            "execution_id": execution_id,
            "language": language,
            "cpu_request": cpu_request,
            "memory_request": memory_request,
            "cpu_limit": cpu_limit,
            "memory_limit": memory_limit,
            "status": "active",
            "allocated_at": datetime.now(timezone.utc),
        }
        result = await self._collection.insert_one(doc)
        return result.inserted_id is not None

    async def release_allocation(self, allocation_id: str) -> bool:
        result = await self._collection.update_one(
            {"_id": allocation_id},
            {"$set": {"status": "released", "released_at": datetime.now(timezone.utc)}}
        )
        return result.modified_count > 0
