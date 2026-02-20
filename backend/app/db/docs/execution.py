from datetime import datetime, timezone
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, ConfigDict, Field
from pymongo import IndexModel

from app.domain.enums import ExecutionErrorType, ExecutionStatus, QueuePriority


# Pydantic model required here because Beanie embedded documents must be Pydantic BaseModel subclasses.
# This is NOT an API schema - it defines the MongoDB subdocument structure.
class ResourceUsage(BaseModel):
    execution_time_wall_seconds: float = 0.0
    cpu_time_jiffies: int = 0
    clk_tck_hertz: int = 0
    peak_memory_kb: int = 0

    model_config = ConfigDict(from_attributes=True)


class ExecutionDocument(Document):
    """Execution document as stored in database.

    Copied from ExecutionInDB schema.
    """

    # From ExecutionBase
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    status: ExecutionStatus = ExecutionStatus.QUEUED  # Indexed via Settings.indexes
    stdout: str | None = None
    stderr: str | None = None
    lang: str = "python"
    lang_version: str = "3.11"

    # From ExecutionInDB
    execution_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    created_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: ResourceUsage | None = None
    user_id: Indexed(str) | None = None  # type: ignore[valid-type]
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    priority: QueuePriority = QueuePriority.NORMAL

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "executions"
        use_state_management = True
        indexes = [
            IndexModel([("status", 1)]),
            IndexModel([("priority", 1)]),
        ]
