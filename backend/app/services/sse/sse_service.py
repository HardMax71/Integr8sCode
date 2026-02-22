import dataclasses
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import TypeAdapter

from app.db.repositories import ExecutionRepository
from app.domain.enums import EventType, SSEControlEvent
from app.domain.sse import DomainNotificationSSEPayload, SSEExecutionEventData
from app.services.sse.redis_bus import SSERedisBus

_exec_adapter = TypeAdapter(SSEExecutionEventData)
_notif_adapter = TypeAdapter(DomainNotificationSSEPayload)

_TERMINAL_TYPES: frozenset[EventType | SSEControlEvent] = frozenset({
    EventType.RESULT_STORED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
    EventType.RESULT_FAILED,
})


class SSEService:
    """SSE service — transforms bus events and DB state into SSE wire format."""

    def __init__(
        self,
        bus: SSERedisBus,
        execution_repository: ExecutionRepository,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._bus = bus
        self._execution_repository = execution_repository
        self._logger = logger

    async def create_execution_stream(
        self, execution_id: str, user_id: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        execution = await self._execution_repository.get_execution(execution_id)
        if execution:
            yield {"data": _exec_adapter.dump_json(SSEExecutionEventData(
                event_type=SSEControlEvent.STATUS,
                execution_id=execution.execution_id,
                timestamp=datetime.now(timezone.utc),
                status=execution.status,
            )).decode()}
        async for event in self._bus.listen_execution(execution_id):
            if event.event_type == EventType.RESULT_STORED:
                result = await self._execution_repository.get_execution_result(execution_id)
                event = dataclasses.replace(event, result=result)
            self._logger.info("SSE event", execution_id=execution_id, event_type=event.event_type)
            yield {"data": _exec_adapter.dump_json(event).decode()}
            if event.event_type in _TERMINAL_TYPES:
                return

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        async for payload in self._bus.listen_notifications(user_id):
            yield {"event": "notification", "data": _notif_adapter.dump_json(payload).decode()}
