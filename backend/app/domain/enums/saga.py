from app.core.utils import StringEnum


class SagaState(StringEnum):
    """Saga execution states."""

    _terminal: bool

    CREATED = "created"
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = ("completed", True)
    FAILED = ("failed", True)
    TIMEOUT = ("timeout", True)
    CANCELLED = ("cancelled", True)

    def __new__(cls, value: str, terminal: bool = False) -> "SagaState":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj._terminal = terminal
        return obj

    @property
    def is_terminal(self) -> bool:
        return self._terminal


SAGA_TERMINAL = frozenset(s for s in SagaState if s.is_terminal)
SAGA_ACTIVE = frozenset(s for s in SagaState if not s.is_terminal)
