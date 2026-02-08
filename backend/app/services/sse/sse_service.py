import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from app.core.metrics import ConnectionMetrics
from app.db.repositories.sse_repository import SSERepository
from app.domain.enums import EventType, NotificationChannel, SSEControlEvent
from app.schemas_pydantic.execution import ExecutionResult
from app.schemas_pydantic.notification import NotificationResponse
from app.schemas_pydantic.sse import (
    RedisNotificationMessage,
    RedisSSEMessage,
    SSEExecutionEventData,
)
from app.services.sse.redis_bus import SSERedisBus, SSERedisSubscription
from app.settings import Settings


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
        logger: logging.Logger,
        connection_metrics: ConnectionMetrics,
    ) -> None:
        self.repository = repository
        self.sse_bus = sse_bus
        self.settings = settings
        self.logger = logger
        self.metrics = connection_metrics

    async def create_execution_stream(self, execution_id: str, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        subscription: SSERedisSubscription | None = None
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
                msg: RedisSSEMessage | None = await subscription.get(RedisSSEMessage)
                if not msg:
                    continue

                self.logger.info(
                    "Received Redis message for execution",
                    extra={"execution_id": execution_id, "event_type": str(msg.event_type)},
                )
                try:
                    sse_event = await self._build_sse_event_from_redis(execution_id, msg)
                    yield self._format_sse_event(sse_event)

                    if msg.event_type in self.TERMINAL_EVENT_TYPES:
                        self.logger.info(
                            "Terminal event for execution",
                            extra={"execution_id": execution_id, "event_type": str(msg.event_type)},
                        )
                        return
                except Exception as e:
                    self.logger.warning(
                        "Failed to process SSE message",
                        extra={"execution_id": execution_id, "event_type": str(msg.event_type), "error": str(e)},
                    )
        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            self.metrics.decrement_sse_connections("executions")
            self.logger.info("SSE connection closed", extra={"execution_id": execution_id})

    async def _build_sse_event_from_redis(self, execution_id: str, msg: RedisSSEMessage) -> SSEExecutionEventData:
        """Build typed SSE event from Redis message."""
        result: ExecutionResult | None = None
        if msg.event_type == EventType.RESULT_STORED:
            exec_domain = await self.repository.get_execution(execution_id)
            if exec_domain:
                result = ExecutionResult.model_validate(exec_domain)

        return SSEExecutionEventData.model_validate(
            {
                **msg.data,
                "event_type": msg.event_type,
                "execution_id": execution_id,
                "result": result,
            }
        )

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        subscription: SSERedisSubscription | None = None
        try:
            subscription = await self.sse_bus.open_notification_subscription(user_id)
            self.logger.info("Notification subscription opened", extra={"user_id": user_id})

            while True:
                redis_msg = await subscription.get(RedisNotificationMessage)
                if not redis_msg:
                    continue

                notification = NotificationResponse(
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
                yield {"event": "notification", "data": notification.model_dump_json()}
        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            self.logger.info("Notification stream closed", extra={"user_id": user_id})

    def _format_sse_event(self, event: SSEExecutionEventData) -> dict[str, Any]:
        """Format typed SSE event for sse-starlette."""
        return {"data": event.model_dump_json(exclude_none=True)}
