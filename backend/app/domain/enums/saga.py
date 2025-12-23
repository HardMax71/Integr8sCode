from app.core.utils import StringEnum


class SagaState(StringEnum):
    """Saga execution states."""

    CREATED = "created"
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
