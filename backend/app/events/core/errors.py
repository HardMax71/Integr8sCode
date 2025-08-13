"""Error types for event system."""


class EventError(Exception):
    """Base exception for event system errors."""
    pass


class ConsumerError(EventError):
    """Base exception for consumer errors."""
    pass


class DeserializationError(EventError):
    """Raised when event deserialization fails."""
    pass


class HandlerError(EventError):
    """Raised when event handler fails."""
    pass


class CircuitBreakerError(EventError):
    """Raised when circuit breaker is open."""
    pass
