from typing import Any, Dict
from uuid import uuid4

from pydantic import ConfigDict, Field
from pydantic_avro import AvroBase  # type: ignore[attr-defined]

from app.domain.enums.common import Environment


class EventMetadata(AvroBase):
    """Unified event metadata for auditing and tracing."""

    service_name: str
    service_version: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True, use_enum_values=True)

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        return self.model_dump(exclude_none=exclude_none)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventMetadata":
        return cls(
            service_name=data.get("service_name", "unknown"),
            service_version=data.get("service_version", "1.0"),
            correlation_id=data.get("correlation_id", str(uuid4())),
            user_id=data.get("user_id"),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            environment=data.get("environment", Environment.PRODUCTION),
        )

    def with_correlation(self, correlation_id: str) -> "EventMetadata":
        return self.model_copy(update={"correlation_id": correlation_id})

    def with_user(self, user_id: str) -> "EventMetadata":
        return self.model_copy(update={"user_id": user_id})

    def ensure_correlation_id(self) -> "EventMetadata":
        if self.correlation_id:
            return self
        return self.model_copy(update={"correlation_id": str(uuid4())})
