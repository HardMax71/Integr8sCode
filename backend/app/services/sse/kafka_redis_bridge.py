"""SSE Kafka Redis Bridge - stateless event handler.

Bridges Kafka events to Redis channels for SSE delivery.
No lifecycle management - worker entrypoint handles the consume loop.
"""

from __future__ import annotations

import logging

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.services.sse.redis_bus import SSERedisBus

# Event types relevant for SSE streaming
RELEVANT_EVENT_TYPES: set[EventType] = {
    EventType.EXECUTION_REQUESTED,
    EventType.EXECUTION_QUEUED,
    EventType.EXECUTION_STARTED,
    EventType.EXECUTION_RUNNING,
    EventType.EXECUTION_COMPLETED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
    EventType.EXECUTION_CANCELLED,
    EventType.RESULT_STORED,
    EventType.POD_CREATED,
    EventType.POD_SCHEDULED,
    EventType.POD_RUNNING,
    EventType.POD_SUCCEEDED,
    EventType.POD_FAILED,
    EventType.POD_TERMINATED,
    EventType.POD_DELETED,
}


class SSEKafkaRedisBridge:
    """Stateless SSE bridge - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    Worker entrypoint handles the consume loop.
    """

    def __init__(
        self,
        sse_bus: SSERedisBus,
        logger: logging.Logger,
    ) -> None:
        self._sse_bus = sse_bus
        self._logger = logger

    @staticmethod
    def get_relevant_event_types() -> set[EventType]:
        """Get event types that should be routed to SSE.

        Helper for worker entrypoint to know which topics to subscribe to.
        """
        return RELEVANT_EVENT_TYPES

    async def handle_event(self, event: DomainEvent) -> None:
        """Handle an event and route to SSE bus.

        Called by worker entrypoint for each event from consume loop.
        """
        data = event.model_dump()
        execution_id = data.get("execution_id")

        if not execution_id:
            self._logger.debug(f"Event {event.event_type} has no execution_id")
            return

        try:
            await self._sse_bus.publish_event(execution_id, event)
            self._logger.debug(f"Published {event.event_type} to Redis for {execution_id}")
        except Exception as e:
            self._logger.error(
                f"Failed to publish {event.event_type} to Redis for {execution_id}: {e}",
                exc_info=True,
            )

    async def get_status(self) -> dict[str, list[str]]:
        """Get bridge status."""
        return {
            "relevant_event_types": [str(et) for et in RELEVANT_EVENT_TYPES],
        }
