from __future__ import annotations

import logging

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.services.sse.redis_bus import SSERedisBus

# Events that should be routed to SSE clients
SSE_RELEVANT_EVENTS: frozenset[EventType] = frozenset([
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
])


class SSEEventRouter:
    """Routes domain events to Redis channels for SSE delivery.

    Stateless service that extracts execution_id from events and publishes
    them to Redis via SSERedisBus. Each execution_id has its own channel.

    Used by the SSE bridge worker (run_sse_bridge.py) via FastStream.
    """

    def __init__(self, sse_bus: SSERedisBus, logger: logging.Logger) -> None:
        self._sse_bus = sse_bus
        self._logger = logger

    async def route_event(self, event: DomainEvent) -> None:
        """Route an event to Redis for SSE delivery."""
        data = event.model_dump()
        execution_id = data.get("execution_id")

        if not execution_id:
            self._logger.debug(f"Event {event.event_type} has no execution_id")
            return

        try:
            await self._sse_bus.publish_event(execution_id, event)
            self._logger.info(f"Published {event.event_type} to Redis for {execution_id}")
        except Exception as e:
            self._logger.error(
                f"Failed to publish {event.event_type} to Redis for {execution_id}: {e}",
                exc_info=True,
            )
