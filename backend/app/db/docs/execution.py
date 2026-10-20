import dataclasses
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import IndexModel

from app.domain.enums import ExecutionErrorType, ExecutionStatus, QueuePriority
from app.domain.events import ResourceUsageDomain
from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION


class ExecutionDocument(Document):
    """Execution document as stored in database.

    Copied from ExecutionInDB schema.
    """

    # From ExecutionBase
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    status: ExecutionStatus = ExecutionStatus.QUEUED  # Indexed via Settings.indexes
    stdout: str | None = None
    stderr: str | None = None
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION

    # From ExecutionInDB
    execution_id: Annotated[str, Indexed(unique=True)] = Field(default_factory=lambda: str(uuid4()))
    created_at: Annotated[datetime, Indexed()] = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: ResourceUsageDomain | None = None
    user_id: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    priority: QueuePriority = QueuePriority.NORMAL

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "executions"
        use_state_management = True
        bson_encoders = {ResourceUsageDomain: dataclasses.asdict}
        indexes = [
            IndexModel([("status", 1)]),
            IndexModel([("priority", 1)]),
        ]
