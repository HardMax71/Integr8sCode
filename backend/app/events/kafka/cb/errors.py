class CircuitBreakerError(Exception):
    """Circuit breaker is open"""
    pass


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass
