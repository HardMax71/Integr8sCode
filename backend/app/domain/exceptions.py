class DomainError(Exception):
    """Base for all domain errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(DomainError):
    """Entity not found (maps to 404)."""

    def __init__(self, entity: str, identifier: str) -> None:
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} '{identifier}' not found")


class ValidationError(DomainError):
    """Business validation failed (maps to 422)."""

    pass


class ThrottledError(DomainError):
    """Rate limit exceeded (maps to 429)."""

    pass


class ConflictError(DomainError):
    """State conflict - duplicate, already exists, etc (maps to 409)."""

    pass


class UnauthorizedError(DomainError):
    """Authentication required (maps to 401)."""

    pass


class ForbiddenError(DomainError):
    """Authenticated but not permitted (maps to 403)."""

    pass


class InvalidStateError(DomainError):
    """Invalid state for operation (maps to 400)."""

    pass


class AccountLockedError(DomainError):
    """Account temporarily locked (maps to 423)."""

    pass


class InfrastructureError(DomainError):
    """Infrastructure failure - DB, Kafka, K8s, etc (maps to 500)."""

    pass
