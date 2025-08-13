"""Event serializer for handling JSON and typed event deserialization."""

import json
from typing import Any

from app.core.logging import logger
from app.schemas_avro.event_schemas import BaseEvent, deserialize_event


class EventSerializer:
    """Serializer that handles JSON to typed event conversion."""
    
    def serialize(self, event: BaseEvent | dict[str, Any]) -> bytes:
        """Serialize event to JSON bytes."""
        if isinstance(event, BaseEvent):
            return event.model_dump_json().encode('utf-8')
        return json.dumps(event).encode('utf-8')
    
    def deserialize(self, data: bytes, topic: str) -> BaseEvent:
        """Deserialize JSON bytes to typed event.
        
        Args:
            data: JSON bytes
            topic: Kafka topic (not used for JSON deserialization)
            
        Returns:
            Typed event object
            
        Raises:
            ValueError: If deserialization fails
        """
        try:
            # First deserialize as JSON
            event_dict = json.loads(data.decode('utf-8'))
            
            # Then convert to typed event
            return deserialize_event(event_dict)
        except Exception as e:
            logger.error(f"Failed to deserialize event: {e}")
            raise ValueError(f"Failed to deserialize event: {e}") from e
