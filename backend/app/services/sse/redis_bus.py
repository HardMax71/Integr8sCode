from __future__ import annotations

import dataclasses
from collections.abc import AsyncGenerator

import redis.asyncio as redis
import structlog
from pydantic import TypeAdapter

from app.domain.events import DomainEvent
from app.domain.sse import RedisNotificationMessage, SSEExecutionEventData

_sse_event_adapter = TypeAdapter(SSEExecutionEventData)
_sse_fields = frozenset(f.name for f in dataclasses.fields(SSEExecutionEventData))
_notif_msg_adapter = TypeAdapter(RedisNotificationMessage)


class SSERedisBus:
    """Redis-backed pub/sub bus for SSE event fan-out across workers."""

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: structlog.stdlib.BoundLogger,
        exec_prefix: str = "sse:exec:",
        notif_prefix: str = "sse:notif:",
    ) -> None:
        self._redis = redis_client
        self.logger = logger
        self._exec_prefix = exec_prefix
        self._notif_prefix = notif_prefix

    def _exec_channel(self, execution_id: str) -> str:
        return f"{self._exec_prefix}{execution_id}"

    def _notif_channel(self, user_id: str) -> str:
        return f"{self._notif_prefix}{user_id}"

    async def publish_event(self, execution_id: str, event: DomainEvent) -> None:
        sse_event = _sse_event_adapter.validate_python(
            {k: v for k, v in event.model_dump().items() if k in _sse_fields}
        )
        await self._redis.publish(
            self._exec_channel(execution_id), _sse_event_adapter.dump_json(sse_event)
        )

    async def publish_notification(self, user_id: str, notification: RedisNotificationMessage) -> None:
        """Publish a typed notification message to Redis for SSE delivery."""
        await self._redis.publish(self._notif_channel(user_id), _notif_msg_adapter.dump_json(notification))

    async def listen_execution(self, execution_id: str) -> AsyncGenerator[SSEExecutionEventData, None]:
        async with self._redis.pubsub() as pubsub:
            await pubsub.subscribe(self._exec_channel(execution_id))
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield _sse_event_adapter.validate_json(message["data"])

    async def listen_notifications(self, user_id: str) -> AsyncGenerator[RedisNotificationMessage, None]:
        async with self._redis.pubsub() as pubsub:
            await pubsub.subscribe(self._notif_channel(user_id))
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield _notif_msg_adapter.validate_json(message["data"])
