import dataclasses
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from pydantic import TypeAdapter

from app.db.repositories import ExecutionRepository
from app.domain.enums import EventType, SSEControlEvent, UserRole
from app.domain.exceptions import ForbiddenError
from app.domain.execution import ExecutionNotFoundError
from app.domain.execution.models import DomainExecution
from app.domain.sse import DomainNotificationSSEPayload, DomainReplaySSEPayload, SSEExecutionEventData
from app.services.sse.redis_bus import SSERedisBus

_exec_adapter = TypeAdapter(SSEExecutionEventData)
_notif_adapter = TypeAdapter(DomainNotificationSSEPayload)
_replay_adapter = TypeAdapter(DomainReplaySSEPayload)

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
        self, execution_id: str, user_id: str, user_role: UserRole
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Eagerly validate access then return the event stream generator.

        Raises ExecutionNotFoundError or ForbiddenError before any streaming
        begins, so FastAPI's exception handlers can return a proper HTTP error
        response instead of crashing inside the SSE task group.
        """
        execution = await self._execution_repository.get_execution(execution_id)
        if not execution:
            raise ExecutionNotFoundError(execution_id)
        if execution.user_id and execution.user_id != user_id and user_role != UserRole.ADMIN:
            raise ForbiddenError("Access denied")
        return self._execution_pipeline(execution)

    async def _execution_pipeline(
        self, execution: DomainExecution
    ) -> AsyncGenerator[dict[str, Any], None]:
        execution_id = execution.execution_id
        yield {"data": _exec_adapter.dump_json(SSEExecutionEventData(
            event_type=SSEControlEvent.STATUS,
            execution_id=execution_id,
            timestamp=execution.updated_at,
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

    async def create_replay_stream(
        self, initial_status: DomainReplaySSEPayload
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Return the replay event stream generator.

        Caller (route) handles validation and initial DB fetch.
        """
        return self._replay_pipeline(initial_status)

    async def _replay_pipeline(
        self, initial_status: DomainReplaySSEPayload
    ) -> AsyncGenerator[dict[str, Any], None]:
        session_id = initial_status.session_id
        yield {"data": _replay_adapter.dump_json(initial_status).decode()}
        if initial_status.status.is_terminal:
            return
        async for status in self._bus.listen_replay(session_id):
            self._logger.info("SSE replay event", session_id=session_id, status=status.status)
            yield {"data": _replay_adapter.dump_json(status).decode()}
            if status.status.is_terminal:
                return
