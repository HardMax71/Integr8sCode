from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from app.domain.enums.common import Environment


@dataclass(config=ConfigDict(from_attributes=True))
class EventMetadata:
    """Domain event metadata for auditing and tracing."""

    service_name: str
    service_version: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
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

    def with_correlation(self, correlation_id: str) -> "EventMetadata":
        return replace(self, correlation_id=correlation_id)

    def with_user(self, user_id: str) -> "EventMetadata":
        return replace(self, user_id=user_id)
