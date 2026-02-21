from __future__ import annotations

import dataclasses
from typing import Any, TypeVar

import redis.asyncio as redis
import structlog
from pydantic import TypeAdapter

from app.domain.events import DomainEvent
from app.domain.sse import RedisNotificationMessage, SSEExecutionEventData

T = TypeVar("T")

_sse_event_adapter = TypeAdapter(SSEExecutionEventData)
_sse_fields = frozenset(f.name for f in dataclasses.fields(SSEExecutionEventData))
_notif_msg_adapter = TypeAdapter(RedisNotificationMessage)


class SSERedisSubscription:
    """Subscription wrapper for Redis pubsub with typed message parsing."""

    def __init__(self, pubsub: redis.client.PubSub, channel: str, logger: structlog.stdlib.BoundLogger) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self.logger = logger

    async def get(self, model: type[T], adapter: TypeAdapter[Any] | None = None) -> T | None:
        """Get next typed message from the subscription."""
        msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if not msg or msg.get("type") != "message":
            return None
        try:
            ta = adapter or TypeAdapter(model)
            return ta.validate_json(msg["data"])  # type: ignore[no-any-return]
        except Exception as e:
            self.logger.warning(
                f"Failed to parse Redis message on channel {self._channel}: {e}",
                channel=self._channel,
                model=model.__name__,
            )
            return None

    async def close(self) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]


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

    async def open_subscription(self, execution_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._exec_channel(execution_id)
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)
        return SSERedisSubscription(pubsub, channel, self.logger)

    async def publish_notification(self, user_id: str, notification: RedisNotificationMessage) -> None:
        """Publish a typed notification message to Redis for SSE delivery."""
        await self._redis.publish(self._notif_channel(user_id), _notif_msg_adapter.dump_json(notification))

    async def open_notification_subscription(self, user_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._notif_channel(user_id)
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)
        return SSERedisSubscription(pubsub, channel, self.logger)
