class IntegrationException(Exception):
    """Exception raised for integration errors."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class AuthenticationError(Exception):
    """Exception raised for authentication errors."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ServiceError(Exception):
    """Exception raised for service-related errors."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)
