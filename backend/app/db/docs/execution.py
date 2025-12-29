from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, ConfigDict, Field
from pymongo import IndexModel

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType


class ResourceUsage(BaseModel):
    """Model for execution resource usage (embedded document).

    Copied from execution.py ResourceUsage.
    """

    execution_time_wall_seconds: float | None = Field(
        default=None, description="Wall clock execution time in seconds"
    )
    cpu_time_jiffies: int | None = Field(
        default=None, description="CPU time in jiffies (multiply by 10 for milliseconds)"
    )
    clk_tck_hertz: int | None = Field(default=None, description="Clock ticks per second (usually 100)")
    peak_memory_kb: int | None = Field(default=None, description="Peak memory usage in KB")

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

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    class Settings:
        name = "executions"
        use_state_management = True
        indexes = [
            IndexModel([("status", 1)]),
        ]


