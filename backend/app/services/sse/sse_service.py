import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import TypeAdapter

from app.core.metrics import ConnectionMetrics
from app.db.repositories import SSERepository
from app.domain.enums import EventType, NotificationChannel, SSEControlEvent
from app.domain.execution.models import ExecutionResultDomain
from app.domain.sse import (
    DomainNotificationSSEPayload,
    RedisNotificationMessage,
    RedisSSEMessage,
    SSEExecutionEventData,
)
from app.services.sse.redis_bus import SSERedisBus, SSERedisSubscription, _notif_msg_adapter, _sse_msg_adapter
from app.settings import Settings

_sse_event_adapter = TypeAdapter(SSEExecutionEventData)
_notif_payload_adapter = TypeAdapter(DomainNotificationSSEPayload)
_exec_result_fields = set(ExecutionResultDomain.__dataclass_fields__)


class SSEService:
    """SSE service for streaming execution events and notifications.

    Shutdown/disconnect handling is delegated to sse-starlette's
    ``EventSourceResponse`` which cancels the generator on client
    disconnect or server SIGTERM (via ``AppStatus.should_exit``).
    The generator's ``finally`` block handles cleanup.
    """

    # Terminal event types that should close the SSE stream
    TERMINAL_EVENT_TYPES: set[EventType] = {
        EventType.RESULT_STORED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
        EventType.RESULT_FAILED,
    }

    def __init__(
        self,
        repository: SSERepository,
        sse_bus: SSERedisBus,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
        connection_metrics: ConnectionMetrics,
    ) -> None:
        self.repository = repository
        self.sse_bus = sse_bus
        self.settings = settings
        self.logger = logger
        self.metrics = connection_metrics

    async def create_execution_stream(self, execution_id: str, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        subscription: SSERedisSubscription | None = None
        start_time = datetime.now(timezone.utc)
        self.metrics.increment_sse_connections("executions")
        try:
            yield self._format_sse_event(
                SSEExecutionEventData(
                    event_type=SSEControlEvent.CONNECTED,
                    execution_id=execution_id,
                    timestamp=datetime.now(timezone.utc),
                )
            )

            subscription = await self.sse_bus.open_subscription(execution_id)
            yield self._format_sse_event(
                SSEExecutionEventData(
                    event_type=SSEControlEvent.SUBSCRIBED,
                    execution_id=execution_id,
                    timestamp=datetime.now(timezone.utc),
                    message="Redis subscription established",
                )
            )

            initial_status = await self.repository.get_execution_status(execution_id)
            if initial_status:
                yield self._format_sse_event(
                    SSEExecutionEventData(
                        event_type=SSEControlEvent.STATUS,
                        execution_id=initial_status.execution_id,
                        timestamp=initial_status.timestamp,
                        status=initial_status.status,
                    )
                )
                self.metrics.record_sse_message_sent("executions", "status")

            while True:
                msg: RedisSSEMessage | None = await subscription.get(RedisSSEMessage, _sse_msg_adapter)
                if not msg:
                    continue

                self.logger.info(
                    "Received Redis message for execution",
                    execution_id=execution_id,
                    event_type=msg.event_type,
                )
                try:
                    sse_event = await self._build_sse_event_from_redis(execution_id, msg)
                    yield self._format_sse_event(sse_event)

                    if msg.event_type in self.TERMINAL_EVENT_TYPES:
                        self.logger.info(
                            "Terminal event for execution",
                            execution_id=execution_id,
                            event_type=msg.event_type,
                        )
                        return
                except Exception as e:
                    self.logger.warning(
                        "Failed to process SSE message",
                        execution_id=execution_id,
                        event_type=msg.event_type,
                        error=str(e),
                    )
        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics.record_sse_connection_duration(duration, "executions")
            self.metrics.decrement_sse_connections("executions")
            self.logger.info("SSE connection closed", execution_id=execution_id)

    async def _build_sse_event_from_redis(self, execution_id: str, msg: RedisSSEMessage) -> SSEExecutionEventData:
        """Build typed SSE event from Redis message.

        Uses validate_python to coerce JSON primitives (str → enum, ISO str → datetime,
        dict → dataclass) back to proper types after the Redis JSON round-trip.
        Extra keys from the original domain event are ignored.
        """
        result: ExecutionResultDomain | None = None
        if msg.event_type == EventType.RESULT_STORED:
            execution = await self.repository.get_execution(execution_id)
            if execution:
                result = ExecutionResultDomain(**{
                    k: v for k, v in execution.__dict__.items() if k in _exec_result_fields
                })
            else:
                self.logger.warning(
                    "Execution not found for RESULT_STORED event",
                    execution_id=execution_id,
                )

        return _sse_event_adapter.validate_python({
            "event_type": msg.event_type,
            **msg.data,
            "execution_id": execution_id,
            "result": result,
        })

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        subscription: SSERedisSubscription | None = None
        try:
            subscription = await self.sse_bus.open_notification_subscription(user_id)
            self.logger.info("Notification subscription opened", user_id=user_id)

            while True:
                redis_msg = await subscription.get(RedisNotificationMessage, _notif_msg_adapter)
                if not redis_msg:
                    continue

                payload = DomainNotificationSSEPayload(
                    notification_id=redis_msg.notification_id,
                    channel=NotificationChannel.IN_APP,
                    status=redis_msg.status,
                    subject=redis_msg.subject,
                    body=redis_msg.body,
                    action_url=redis_msg.action_url,
                    created_at=redis_msg.created_at,
                    read_at=None,
                    severity=redis_msg.severity,
                    tags=redis_msg.tags,
                )
                yield {"event": "notification", "data": _notif_payload_adapter.dump_json(payload).decode()}
        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            self.logger.info("Notification stream closed", user_id=user_id)

    def _format_sse_event(self, event: SSEExecutionEventData) -> dict[str, Any]:
        """Format typed SSE event for sse-starlette."""
        return {"data": _sse_event_adapter.dump_json(event, exclude_none=True).decode()}
