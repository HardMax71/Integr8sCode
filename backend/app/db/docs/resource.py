from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import ConfigDict, Field

from app.domain.enums import AllocationStatus


class ResourceAllocationDocument(Document):
    """Resource allocation bookkeeping document used by saga steps.

    Based on ResourceAllocationRepository document structure.
    """

    allocation_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    execution_id: Indexed(str)  # type: ignore[valid-type]
    language: Indexed(str)  # type: ignore[valid-type]
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
    status: Indexed(str) = AllocationStatus.ACTIVE  # type: ignore[valid-type]
    allocated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    released_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "resource_allocations"
        use_state_management = True
