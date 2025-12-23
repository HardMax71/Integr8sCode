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
