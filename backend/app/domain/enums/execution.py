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


class CancelStatus(StringEnum):
    """Outcome of a cancel request."""

    ALREADY_CANCELLED = "already_cancelled"
    CANCELLATION_REQUESTED = "cancellation_requested"
