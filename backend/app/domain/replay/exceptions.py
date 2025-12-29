from app.domain.exceptions import InfrastructureError, NotFoundError


class ReplaySessionNotFoundError(NotFoundError):
    """Raised when a replay session is not found."""

    def __init__(self, session_id: str) -> None:
        super().__init__("Replay session", session_id)


class ReplayOperationError(InfrastructureError):
    """Raised when a replay operation fails."""

    def __init__(self, session_id: str, operation: str, reason: str) -> None:
        self.session_id = session_id
        self.operation = operation
        super().__init__(f"Failed to {operation} session '{session_id}': {reason}")
