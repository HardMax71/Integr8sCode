from app.core.utils import StringEnum


class QueuePriority(StringEnum):
    """Execution priority, ordered highest to lowest."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


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
