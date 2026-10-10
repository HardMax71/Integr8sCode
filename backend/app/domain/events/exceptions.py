from app.domain.exceptions import NotFoundError


class EventNotFoundError(NotFoundError):
    """Raised when a stored event is not found."""

    def __init__(self, event_id: str) -> None:
        super().__init__("Event", event_id)
