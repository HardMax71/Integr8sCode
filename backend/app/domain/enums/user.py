from app.core.utils import StringEnum


class UserRole(StringEnum):
    """User roles in the system."""

    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"
