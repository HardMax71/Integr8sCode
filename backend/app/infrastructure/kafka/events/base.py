from datetime import datetime, timezone
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import ConfigDict, Field
from pydantic_avro import AvroBase

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.metadata import EventMetadata


class BaseEvent(AvroBase):
    """Base class for all events."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None
    metadata: EventMetadata

    # Each subclass must define its topic
    topic: ClassVar[KafkaTopic]

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )

    def to_dict(self) -> dict[str, Any]:
        # Use mode='json' to properly serialize datetime objects to ISO strings
        return self.model_dump(by_alias=True, mode='json')

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)
