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

    @property
    def is_terminal(self) -> bool:
        """True if this status represents a final state (no further transitions)."""
        return self in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMEOUT,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.ERROR,
        )
