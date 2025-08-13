from enum import IntEnum, StrEnum


class CircuitState(IntEnum):
    """Circuit breaker states."""
    CLOSED = 0  # Normal operation
    OPEN = 1  # Failing, reject requests
    HALF_OPEN = 2  # Testing if service recovered


class CircuitStateStr(StrEnum):
    """Circuit breaker states as strings for general purpose breaker"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
