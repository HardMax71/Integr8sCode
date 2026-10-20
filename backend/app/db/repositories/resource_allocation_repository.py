from datetime import datetime, timezone

import structlog

from app.db.docs import ResourceAllocationDocument


class ResourceAllocationRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def count_active(self, language: str) -> int:
        return await ResourceAllocationDocument.find(
            ResourceAllocationDocument.status == "active",
            ResourceAllocationDocument.language == language,
        ).count()

    async def create_allocation(self, allocation: ResourceAllocationDocument) -> ResourceAllocationDocument:
        await allocation.insert()
        return allocation

    async def release_allocation(self, allocation_id: str) -> bool:
        doc = await ResourceAllocationDocument.find_one(ResourceAllocationDocument.allocation_id == allocation_id)
        if not doc:
            return False
        await doc.set({"status": "released", "released_at": datetime.now(timezone.utc)})
        return True
