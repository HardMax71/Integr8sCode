import asyncio
import dataclasses
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, TypeVar

import redis.asyncio as redis
import structlog
from pydantic import TypeAdapter

from app.core.metrics import ConnectionMetrics
from app.db import ExecutionRepository
from app.domain.enums import EventType, SSEControlEvent, UserRole
from app.domain.exceptions import ForbiddenError
from app.domain.execution import ExecutionNotFoundError
from app.domain.execution.models import DomainExecution
from app.domain.sse import DomainNotificationSSEPayload, DomainReplaySSEPayload, SSEExecutionEventData
from app.infrastructure.kafka.topics import EXECUTION_PIPELINE_TERMINAL_EVENT_TYPES

_exec_adapter = TypeAdapter(SSEExecutionEventData)
_notif_adapter = TypeAdapter(DomainNotificationSSEPayload)
_replay_adapter = TypeAdapter(DomainReplaySSEPayload)

T = TypeVar("T")


class SSEService:
    """SSE service — publishes events via Redis Streams and transforms them into SSE wire format."""

    _MAXLEN = 100
    _STREAM_TTL = 600

    def __init__(
        self,
        redis_client: redis.Redis,
        execution_repository: ExecutionRepository,
        logger: structlog.stdlib.BoundLogger,
        connection_metrics: ConnectionMetrics,
        exec_prefix: str = "sse:exec:",
        notif_prefix: str = "sse:notif:",
        replay_prefix: str = "sse:replay:",
        poll_interval: float = 0.5,
    ) -> None:
        self._redis = redis_client
        self._execution_repository = execution_repository
        self._logger = logger
        self._metrics = connection_metrics
        self._exec_prefix = exec_prefix
        self._notif_prefix = notif_prefix
        self._replay_prefix = replay_prefix
        self._poll_interval = poll_interval

    async def _xpublish(self, key: str, data: bytes) -> None:
        await self._redis.xadd(key, {"d": data}, maxlen=self._MAXLEN, approximate=True)
        await self._redis.expire(key, self._STREAM_TTL)

    async def publish_event(self, execution_id: str, event: SSEExecutionEventData) -> None:
        await self._xpublish(f"{self._exec_prefix}{execution_id}", _exec_adapter.dump_json(event))

    async def publish_notification(self, user_id: str, notification: DomainNotificationSSEPayload) -> None:
        await self._xpublish(f"{self._notif_prefix}{user_id}", _notif_adapter.dump_json(notification))

    async def publish_replay_status(self, session_id: str, status: DomainReplaySSEPayload) -> None:
        await self._xpublish(f"{self._replay_prefix}{session_id}", _replay_adapter.dump_json(status))

    async def _read_after(self, key: str, last_id: str) -> list[tuple[str, bytes]]:
        result = await self._redis.xread({key: last_id}, count=100)
        if not result:
            return []
        return [(mid, fields[b"d"]) for _, msgs in result for mid, fields in msgs]

    async def _poll_stream(self, key: str, adapter: TypeAdapter[T]) -> AsyncGenerator[T, None]:
        last_id = "0-0"
        while True:
            batch = await self._read_after(key, last_id)
            for msg_id, raw in batch:
                last_id = msg_id
                yield adapter.validate_json(raw)
            if not batch:
                await asyncio.sleep(self._poll_interval)

    async def create_execution_stream(
        self, execution_id: str, user_id: str, user_role: UserRole,
    ) -> AsyncGenerator[dict[str, Any], None]:
        execution = await self._execution_repository.get_execution(execution_id)
        if not execution:
            raise ExecutionNotFoundError(execution_id)
        if execution.user_id and execution.user_id != user_id and user_role != UserRole.ADMIN:
            raise ForbiddenError("Access denied")
        return self._execution_pipeline(execution)

    async def _execution_pipeline(
        self, execution: DomainExecution,
    ) -> AsyncGenerator[dict[str, Any], None]:
        execution_id = execution.execution_id
        start = datetime.now(timezone.utc)
        self._metrics.increment_sse_connections("executions")
        try:
            yield {"data": _exec_adapter.dump_json(SSEExecutionEventData(
                event_type=SSEControlEvent.STATUS,
                execution_id=execution_id,
                timestamp=execution.updated_at,
                status=execution.status,
            )).decode()}
            async for event in self._poll_stream(f"{self._exec_prefix}{execution_id}", _exec_adapter):
                if event.event_type == EventType.RESULT_STORED:
                    result = await self._execution_repository.get_execution_result(execution_id)
                    event = dataclasses.replace(event, result=result)
                self._logger.info("SSE event", execution_id=execution_id, event_type=event.event_type)
                yield {"data": _exec_adapter.dump_json(event).decode()}
                if event.event_type in EXECUTION_PIPELINE_TERMINAL_EVENT_TYPES:
                    return
        finally:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            self._metrics.record_sse_connection_duration(duration, "executions")
            self._metrics.decrement_sse_connections("executions")

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        start = datetime.now(timezone.utc)
        self._metrics.increment_sse_connections("notifications")
        try:
            async for payload in self._poll_stream(f"{self._notif_prefix}{user_id}", _notif_adapter):
                yield {"event": "notification", "data": _notif_adapter.dump_json(payload).decode()}
        finally:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            self._metrics.record_sse_connection_duration(duration, "notifications")
            self._metrics.decrement_sse_connections("notifications")

    async def create_replay_stream(
        self, initial_status: DomainReplaySSEPayload,
    ) -> AsyncGenerator[dict[str, Any], None]:
        return self._replay_pipeline(initial_status)

    async def _replay_pipeline(
        self, initial_status: DomainReplaySSEPayload,
    ) -> AsyncGenerator[dict[str, Any], None]:
        session_id = initial_status.session_id
        yield {"data": _replay_adapter.dump_json(initial_status).decode()}
        if initial_status.status.is_terminal:
            return
        async for status in self._poll_stream(f"{self._replay_prefix}{session_id}", _replay_adapter):
            self._logger.info("SSE replay event", session_id=session_id, status=status.status)
            yield {"data": _replay_adapter.dump_json(status).decode()}
            if status.status.is_terminal:
                return
