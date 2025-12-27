from dataclasses import asdict, dataclass, field, replace
from typing import Any
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

    def to_dict(self, exclude_none: bool = True) -> dict[str, Any]:
        result = asdict(self)
        if isinstance(result.get("environment"), Environment):
            result["environment"] = result["environment"].value
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventMetadata":
        env = data.get("environment", Environment.PRODUCTION)
        if isinstance(env, str):
            env = Environment(env)
        return cls(
            service_name=data.get("service_name", "unknown"),
            service_version=data.get("service_version", "1.0"),
            correlation_id=data.get("correlation_id", str(uuid4())),
            user_id=data.get("user_id"),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            environment=env,
        )

    def with_correlation(self, correlation_id: str) -> "EventMetadata":
        return replace(self, correlation_id=correlation_id)

    def with_user(self, user_id: str) -> "EventMetadata":
        return replace(self, user_id=user_id)
