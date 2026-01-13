from datetime import datetime, timezone
from uuid import uuid4

from app.db.docs import ResourceAllocationDocument
from app.domain.saga import DomainResourceAllocation, DomainResourceAllocationCreate


class ResourceAllocationRepository:
    async def count_active(self, language: str) -> int:
        return await ResourceAllocationDocument.find(
            ResourceAllocationDocument.status == "active",
            ResourceAllocationDocument.language == language,
        ).count()

    async def create_allocation(self, create_data: DomainResourceAllocationCreate) -> DomainResourceAllocation:
        doc = ResourceAllocationDocument(
            allocation_id=str(uuid4()),
            **create_data.model_dump(),
        )
        await doc.insert()
        return DomainResourceAllocation.model_validate(doc, from_attributes=True)

    async def release_allocation(self, allocation_id: str) -> bool:
        doc = await ResourceAllocationDocument.find_one(ResourceAllocationDocument.allocation_id == allocation_id)
        if not doc:
            return False
        await doc.set({"status": "released", "released_at": datetime.now(timezone.utc)})
        return True
