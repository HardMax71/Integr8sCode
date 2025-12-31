from app.domain.exceptions import InfrastructureError, NotFoundError, ValidationError


class ExecutionNotFoundError(NotFoundError):
    """Raised when execution is not found."""

    def __init__(self, execution_id: str) -> None:
        super().__init__("Execution", execution_id)


class RuntimeNotSupportedError(ValidationError):
    """Raised when requested runtime is not supported."""

    def __init__(self, lang: str, version: str) -> None:
        self.lang = lang
        self.version = version
        super().__init__(f"Runtime not supported: {lang} {version}")


class EventPublishError(InfrastructureError):
    """Raised when event publishing fails."""

    def __init__(self, event_type: str, reason: str) -> None:
        self.event_type = event_type
        super().__init__(f"Failed to publish {event_type}: {reason}")
