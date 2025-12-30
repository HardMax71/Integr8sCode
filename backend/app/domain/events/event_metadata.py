from dataclasses import dataclass, field, replace
from uuid import uuid4

from app.domain.enums.common import Environment


@dataclass
class EventMetadata:
    """Domain event metadata for auditing and tracing."""

    service_name: str
    service_version: str
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION

    def with_correlation(self, correlation_id: str) -> "EventMetadata":
        return replace(self, correlation_id=correlation_id)

    def with_user(self, user_id: str) -> "EventMetadata":
        return replace(self, user_id=user_id)
