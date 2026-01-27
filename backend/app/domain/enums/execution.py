from enum import IntEnum

from app.core.utils import StringEnum


class ExecutionStatus(StringEnum):
    """Status of an execution."""

    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "error"


class QueuePriority(IntEnum):
    """Execution queue priorities. Lower value = higher priority."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 5
    LOW = 8
    BACKGROUND = 10
