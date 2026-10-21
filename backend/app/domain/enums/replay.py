from app.core.utils import StringEnum


class ReplayStatus(StringEnum):
    # Unified replay lifecycle across admin + services
    _terminal: bool

    PREVIEW = "preview"  # Dry-run preview state
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = ("completed", True)
    FAILED = ("failed", True)

    def __new__(cls, value: str, terminal: bool = False) -> "ReplayStatus":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj._terminal = terminal
        return obj

    @property
    def is_terminal(self) -> bool:
        return self._terminal


REPLAY_TERMINAL = frozenset(s for s in ReplayStatus if s.is_terminal)
