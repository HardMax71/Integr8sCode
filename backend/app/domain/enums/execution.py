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

    _terminal: bool

    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = ("completed", True)
    FAILED = ("failed", True)
    TIMEOUT = ("timeout", True)
    CANCELLED = ("cancelled", True)
    ERROR = ("error", True)

    def __new__(cls, value: str, terminal: bool = False) -> "ExecutionStatus":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj._terminal = terminal
        return obj

    @property
    def is_terminal(self) -> bool:
        return self._terminal


EXECUTION_TERMINAL = frozenset(s for s in ExecutionStatus if s.is_terminal)
EXECUTION_ACTIVE = frozenset(s for s in ExecutionStatus if not s.is_terminal)


class CancelStatus(StringEnum):
    """Outcome of a cancel request."""

    ALREADY_CANCELLED = "already_cancelled"
    CANCELLATION_REQUESTED = "cancellation_requested"
