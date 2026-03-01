from app.domain.exceptions import ForbiddenError, NotFoundError, UnauthorizedError


class AuthenticationRequiredError(UnauthorizedError):
    """Raised when authentication is required but not provided."""

    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(message)


class InvalidCredentialsError(UnauthorizedError):
    """Raised when credentials are invalid."""

    def __init__(self, message: str = "Invalid credentials") -> None:
        super().__init__(message)


class TokenExpiredError(UnauthorizedError):
    """Raised when a token has expired."""

    def __init__(self) -> None:
        super().__init__("Token has expired")


class CSRFValidationError(ForbiddenError):
    """Raised when CSRF validation fails."""

    def __init__(self, reason: str = "CSRF validation failed") -> None:
        super().__init__(reason)


class AdminAccessRequiredError(ForbiddenError):
    """Raised when admin access is required."""

    def __init__(self, username: str | None = None) -> None:
        self.username = username
        msg = f"Admin access required for user '{username}'" if username else "Admin access required"
        super().__init__(msg)


class AccountDeactivatedError(ForbiddenError):
    """Raised when a deactivated account attempts to log in."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"Account '{username}' is deactivated")


class UserNotFoundError(NotFoundError):
    """Raised when a user is not found."""

    def __init__(self, identifier: str) -> None:
        super().__init__("User", identifier)
