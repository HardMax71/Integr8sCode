class ExecutionServiceError(Exception):
    """Base exception for execution service errors."""

    pass


class RuntimeNotSupportedError(ExecutionServiceError):
    """Raised when requested runtime is not supported."""

    pass


class EventPublishError(ExecutionServiceError):
    """Raised when event publishing fails."""

    pass


class ExecutionNotFoundError(ExecutionServiceError):
    """Raised when execution is not found."""

    pass
