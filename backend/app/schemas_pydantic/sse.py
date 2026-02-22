from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EventType, ExecutionStatus, SSEControlEvent
from app.schemas_pydantic.execution import ExecutionResult


class SSEExecutionEventSchema(BaseModel):
    """API schema for SSE execution stream events.

    All fields are always present. Nullable fields carry null when not applicable:
    event_id is null for control events; status only for the status control event;
    result only for result_stored.
    """

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    event_type: EventType | SSEControlEvent = Field(description="Event type identifier")
    execution_id: str = Field(description="Execution ID")
    timestamp: datetime | None = Field(default=None, description="Event timestamp")
    event_id: str | None = Field(default=None, description="Kafka event ID (null for control events)")
    status: ExecutionStatus | None = Field(default=None, description="Execution status (status control event only)")
    result: ExecutionResult | None = Field(default=None, description="Full execution result (result_stored only)")


__all__ = [
    "SSEExecutionEventSchema",
]
