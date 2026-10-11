from app.domain.enums import ExecutionStatus
from app.domain.exceptions import ForbiddenError, InvalidStateError, NotFoundError, ThrottledError, ValidationError


class ExecutionNotFoundError(NotFoundError):
    """Raised when execution is not found."""

    def __init__(self, execution_id: str) -> None:
        super().__init__("Execution", execution_id)


class ExecutionAccessDeniedError(ForbiddenError):
    """Raised when a non-admin user accesses another user's execution."""

    def __init__(self, execution_id: str) -> None:
        self.execution_id = execution_id
        super().__init__(f"Access denied to execution '{execution_id}'")


class ExecutionNotRetryableError(InvalidStateError):
    """Raised when retrying an execution that hasn't finished yet."""

    def __init__(self, execution_id: str, status: ExecutionStatus) -> None:
        self.execution_id = execution_id
        self.status = status
        super().__init__(f"Cannot retry execution in {status} state")


class ExecutionLimitExceededError(ThrottledError):
    """Raised when a user already has as many executions queued or running as allowed."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"You already have {limit} executions queued or running; wait for one to finish")


class RuntimeNotSupportedError(ValidationError):
    """Raised when requested runtime is not supported."""

    def __init__(self, lang: str, version: str) -> None:
        self.lang = lang
        self.version = version
        super().__init__(f"Runtime not supported: {lang} {version}")


class ExecutionTerminalError(InvalidStateError):
    """Raised when attempting to cancel an execution in a terminal state."""

    def __init__(self, execution_id: str, status: ExecutionStatus) -> None:
        self.execution_id = execution_id
        self.status = status
        super().__init__(f"Cannot cancel execution in {status} state")
