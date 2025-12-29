from dataclasses import asdict
from datetime import datetime, timezone

from app.db.docs import ResourceAllocationDocument
from app.domain.saga import DomainResourceAllocation, DomainResourceAllocationCreate


class ResourceAllocationRepository:

    async def count_active(self, language: str) -> int:
        return await ResourceAllocationDocument.find(
            {"status": "active", "language": language}
        ).count()

    async def create_allocation(self, create_data: DomainResourceAllocationCreate) -> DomainResourceAllocation:
        doc = ResourceAllocationDocument(**asdict(create_data))
        await doc.insert()
        return DomainResourceAllocation(**doc.model_dump(exclude={'id'}))

    async def release_allocation(self, allocation_id: str) -> bool:
        doc = await ResourceAllocationDocument.find_one({"allocation_id": allocation_id})
        if not doc:
            return False
        await doc.set({"status": "released", "released_at": datetime.now(timezone.utc)})
        return True
