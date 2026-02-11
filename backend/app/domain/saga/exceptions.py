from app.domain.enums import SagaState
from app.domain.exceptions import ConflictError, ForbiddenError, InfrastructureError, InvalidStateError, NotFoundError


class SagaNotFoundError(NotFoundError):
    """Raised when a saga is not found."""

    def __init__(self, saga_id: str) -> None:
        super().__init__("Saga", saga_id)


class SagaAccessDeniedError(ForbiddenError):
    """Raised when access to a saga is denied."""

    def __init__(self, saga_id: str, user_id: str) -> None:
        self.saga_id = saga_id
        self.user_id = user_id
        super().__init__(f"Access denied to saga '{saga_id}' for user '{user_id}'")


class SagaInvalidStateError(InvalidStateError):
    """Raised when a saga operation is invalid for the current state."""

    def __init__(self, saga_id: str, current_state: SagaState, operation: str) -> None:
        self.saga_id = saga_id
        self.current_state = current_state
        self.operation = operation
        super().__init__(f"Cannot {operation} saga '{saga_id}' in state '{current_state}'")


class SagaCompensationError(InfrastructureError):
    """Raised when saga compensation fails."""

    def __init__(self, saga_id: str, step: str, reason: str) -> None:
        self.saga_id = saga_id
        self.step = step
        super().__init__(f"Compensation failed for saga '{saga_id}' at step '{step}': {reason}")


class SagaTimeoutError(InfrastructureError):
    """Raised when a saga times out."""

    def __init__(self, saga_id: str, timeout_seconds: int) -> None:
        self.saga_id = saga_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Saga '{saga_id}' timed out after {timeout_seconds}s")


class SagaConcurrencyError(ConflictError):
    """Raised when there's a concurrency conflict with saga operations."""

    def __init__(self, saga_id: str) -> None:
        self.saga_id = saga_id
        super().__init__(f"Concurrency conflict for saga '{saga_id}'")
