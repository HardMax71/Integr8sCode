from app.domain.exceptions import NotFoundError


class ReplaySessionNotFoundError(NotFoundError):
    """Raised when a replay session is not found."""

    def __init__(self, session_id: str) -> None:
        super().__init__("Replay session", session_id)
