class SagaError(Exception):
    """Base exception for saga-related errors."""

    pass


class SagaNotFoundError(SagaError):
    """Raised when a saga is not found."""

    pass


class SagaAccessDeniedError(SagaError):
    """Raised when access to a saga is denied."""

    pass


class SagaInvalidStateError(SagaError):
    """Raised when a saga operation is invalid for the current state."""

    pass


class SagaCompensationError(SagaError):
    """Raised when saga compensation fails."""

    pass


class SagaTimeoutError(SagaError):
    """Raised when a saga times out."""

    pass


class SagaConcurrencyError(SagaError):
    """Raised when there's a concurrency conflict with saga operations."""

    pass
