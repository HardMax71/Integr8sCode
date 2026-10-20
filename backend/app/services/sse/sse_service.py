import dataclasses
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

import structlog
from pydantic import TypeAdapter

from app.db import ExecutionRepository
from app.db.docs import ExecutionDocument
from app.domain.enums import EventType, SSEControlEvent, UserRole
from app.domain.exceptions import ForbiddenError
from app.domain.execution import ExecutionNotFoundError
from app.domain.sse import DomainNotificationSSEPayload, DomainReplaySSEPayload, SSEExecutionEventData
from app.infrastructure.kafka.topics import EXECUTION_PIPELINE_TERMINAL_EVENT_TYPES
from app.services.sse.redis_bus import SSERedisBus

_exec_adapter = TypeAdapter(SSEExecutionEventData)
_notif_adapter = TypeAdapter(DomainNotificationSSEPayload)


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

    async def _execution_pipeline(self, execution: ExecutionDocument) -> AsyncGenerator[dict[str, Any], None]:
        execution_id = execution.execution_id
        yield {
            "data": _exec_adapter.dump_json(
                SSEExecutionEventData(
                    event_type=SSEControlEvent.STATUS,
                    execution_id=execution_id,
                    timestamp=execution.updated_at,
                    status=execution.status,
                )
            ).decode()
        }
        # The terminal events went out before this subscription, so a finished execution gets its result and closes
        if execution.status.is_terminal:
            result = await self._execution_repository.get_terminal_result(execution_id)
            yield {
                "data": _exec_adapter.dump_json(
                    SSEExecutionEventData(
                        event_type=EventType.RESULT_STORED,
                        execution_id=execution_id,
                        timestamp=execution.updated_at,
                        result=result,
                    )
                ).decode()
            }
            return
        async with aclosing(self._bus.listen_execution(execution_id)) as events:
            async for event in events:
                if event.event_type == EventType.RESULT_STORED:
                    result = await self._execution_repository.get_terminal_result(execution_id)
                    event = dataclasses.replace(event, result=result)
                self._logger.info("SSE event", execution_id=execution_id, event_type=event.event_type)
                yield {"data": _exec_adapter.dump_json(event).decode()}
                if event.event_type in EXECUTION_PIPELINE_TERMINAL_EVENT_TYPES:
                    return

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        async with aclosing(self._bus.listen_notifications(user_id)) as payloads:
            async for payload in payloads:
                yield {"event": "notification", "data": _notif_adapter.dump_json(payload).decode()}

    async def create_replay_stream(
        self, initial_status: DomainReplaySSEPayload
    ) -> AsyncGenerator[DomainReplaySSEPayload, None]:
        """Return the replay status stream: the initial status, then each change until a terminal one.

        Caller (route) handles validation, the initial DB fetch and the wire format.
        """
        return self._replay_pipeline(initial_status)

    async def _replay_pipeline(
        self, initial_status: DomainReplaySSEPayload
    ) -> AsyncGenerator[DomainReplaySSEPayload, None]:
        session_id = initial_status.session_id
        yield initial_status
        if initial_status.status.is_terminal:
            return
        async with aclosing(self._bus.listen_replay(session_id)) as statuses:
            async for status in statuses:
                self._logger.info("SSE replay event", session_id=session_id, status=status.status)
                yield status
                if status.status.is_terminal:
                    return
