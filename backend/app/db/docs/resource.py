from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field

from app.domain.enums import AllocationStatus


class ResourceAllocationDocument(Document):
    """Resource allocation bookkeeping document used by saga steps.

    Based on ResourceAllocationRepository document structure.
    """

    allocation_id: Annotated[str, Indexed(unique=True)] = Field(default_factory=lambda: str(uuid4()))
    execution_id: Annotated[str, Indexed()]
    language: Annotated[str, Indexed()]
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
    status: Annotated[str, Indexed()] = AllocationStatus.ACTIVE
    allocated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    released_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "resource_allocations"
        use_state_management = True
