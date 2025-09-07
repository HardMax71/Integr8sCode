from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger


class ResourceAllocationRepository:
    """Repository for resource allocation bookkeeping used by saga steps."""

    def __init__(self, database: AsyncIOMotorDatabase):
        self._db = database
        self._collection: AsyncIOMotorCollection = self._db.get_collection("resource_allocations")

    async def count_active(self, language: str) -> int:
        try:
            return await self._collection.count_documents({
                "status": "active",
                "language": language,
            })
        except Exception as e:
            logger.error(f"Failed to count active allocations: {e}")
            return 0

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
        try:
            await self._collection.insert_one(doc)
            return True
        except Exception as e:
            logger.error(f"Failed to create resource allocation for {allocation_id}: {e}")
            return False

    async def release_allocation(self, allocation_id: str) -> bool:
        try:
            result = await self._collection.update_one(
                {"_id": allocation_id},
                {"$set": {"status": "released", "released_at": datetime.now(timezone.utc)}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to release resource allocation {allocation_id}: {e}")
            return False

