from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog
from pydantic import TypeAdapter

from app.core.metrics import ConnectionMetrics
from app.domain.sse import DomainNotificationSSEPayload, SSEExecutionEventData

_sse_event_adapter = TypeAdapter(SSEExecutionEventData)
_notif_payload_adapter = TypeAdapter(DomainNotificationSSEPayload)


class SSERedisBus:
    """Redis-backed pub/sub bus for SSE event fan-out across workers."""

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: structlog.stdlib.BoundLogger,
        connection_metrics: ConnectionMetrics,
        exec_prefix: str = "sse:exec:",
        notif_prefix: str = "sse:notif:",
    ) -> None:
        self._redis = redis_client
        self.logger = logger
        self._metrics = connection_metrics
        self._exec_prefix = exec_prefix
        self._notif_prefix = notif_prefix

    def _exec_channel(self, execution_id: str) -> str:
        return f"{self._exec_prefix}{execution_id}"

    def _notif_channel(self, user_id: str) -> str:
        return f"{self._notif_prefix}{user_id}"

    async def publish_event(self, execution_id: str, event: SSEExecutionEventData) -> None:
        await self._redis.publish(self._exec_channel(execution_id), _sse_event_adapter.dump_json(event))

    async def publish_notification(self, user_id: str, notification: DomainNotificationSSEPayload) -> None:
        await self._redis.publish(self._notif_channel(user_id), _notif_payload_adapter.dump_json(notification))

    async def listen_execution(self, execution_id: str) -> AsyncGenerator[SSEExecutionEventData, None]:
        start = datetime.now(timezone.utc)
        self._metrics.increment_sse_connections("executions")
        self.logger.info("SSE execution stream opened", execution_id=execution_id)
        try:
            async with self._redis.pubsub(ignore_subscribe_messages=True) as pubsub:
                await pubsub.subscribe(self._exec_channel(execution_id))
                async for message in pubsub.listen():
                    yield _sse_event_adapter.validate_json(message["data"])
        finally:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            self._metrics.record_sse_connection_duration(duration, "executions")
            self._metrics.decrement_sse_connections("executions")
            self.logger.info("SSE execution stream closed", execution_id=execution_id)

    async def listen_notifications(self, user_id: str) -> AsyncGenerator[DomainNotificationSSEPayload, None]:
        self._metrics.increment_sse_connections("notifications")
        self.logger.info("SSE notification stream opened", user_id=user_id)
        try:
            async with self._redis.pubsub(ignore_subscribe_messages=True) as pubsub:
                await pubsub.subscribe(self._notif_channel(user_id))
                async for message in pubsub.listen():
                    yield _notif_payload_adapter.validate_json(message["data"])
        finally:
            self._metrics.decrement_sse_connections("notifications")
            self.logger.info("SSE notification stream closed", user_id=user_id)
