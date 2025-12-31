from uuid import uuid4

from pydantic import ConfigDict, Field
from pydantic_avro import AvroBase  # type: ignore[attr-defined]

from app.domain.enums.common import Environment


class AvroEventMetadata(AvroBase):
    """Unified event metadata for auditing and tracing."""

    service_name: str
    service_version: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True, use_enum_values=True)

    def with_correlation(self, correlation_id: str) -> "AvroEventMetadata":
        return self.model_copy(update={"correlation_id": correlation_id})

    def with_user(self, user_id: str) -> "AvroEventMetadata":
        return self.model_copy(update={"user_id": user_id})

    def ensure_correlation_id(self) -> "AvroEventMetadata":
        if self.correlation_id:
            return self
        return self.model_copy(update={"correlation_id": str(uuid4())})
