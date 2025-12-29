from app.domain.exceptions import NotFoundError, ThrottledError, ValidationError


class NotificationNotFoundError(NotFoundError):
    """Raised when a notification is not found."""

    def __init__(self, notification_id: str) -> None:
        super().__init__("Notification", notification_id)


class NotificationThrottledError(ThrottledError):
    """Raised when notification rate limit is exceeded."""

    def __init__(self, user_id: str, limit: int, window_hours: int) -> None:
        self.user_id = user_id
        self.limit = limit
        self.window_hours = window_hours
        super().__init__(f"Rate limit exceeded for user '{user_id}': max {limit} per {window_hours}h")


class NotificationValidationError(ValidationError):
    """Raised when notification validation fails."""

    pass
