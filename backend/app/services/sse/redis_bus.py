from __future__ import annotations

from typing import Type, TypeVar

import redis.asyncio as redis
from pydantic import BaseModel

from app.infrastructure.kafka.events.base import BaseEvent
from app.schemas_pydantic.sse import RedisNotificationMessage, RedisSSEMessage

T = TypeVar("T", bound=BaseModel)


class SSERedisSubscription:
    """Subscription wrapper for Redis pubsub with typed message parsing."""

    def __init__(self, pubsub: redis.client.PubSub, channel: str) -> None:
        self._pubsub = pubsub
        self._channel = channel

    async def get(self, model: Type[T], timeout: float = 0.5) -> T | None:
        """Get next typed message from the subscription."""
        msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if not msg or msg.get("type") != "message":
            return None
        try:
            return model.model_validate_json(msg["data"])
        except Exception:
            return None

    async def close(self) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class SSERedisBus:
    """Redis-backed pub/sub bus for SSE event fan-out across workers."""

    def __init__(
            self, redis_client: redis.Redis, exec_prefix: str = "sse:exec:", notif_prefix: str = "sse:notif:"
    ) -> None:
        self._redis = redis_client
        self._exec_prefix = exec_prefix
        self._notif_prefix = notif_prefix

    def _exec_channel(self, execution_id: str) -> str:
        return f"{self._exec_prefix}{execution_id}"

    def _notif_channel(self, user_id: str) -> str:
        return f"{self._notif_prefix}{user_id}"

    async def publish_event(self, execution_id: str, event: BaseEvent) -> None:
        message = RedisSSEMessage(
            event_type=event.event_type,
            execution_id=execution_id,
            data=event.model_dump(mode="json"),
        )
        await self._redis.publish(self._exec_channel(execution_id), message.model_dump_json())

    async def open_subscription(self, execution_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._exec_channel(execution_id)
        await pubsub.subscribe(channel)
        return SSERedisSubscription(pubsub, channel)

    async def publish_notification(self, user_id: str, notification: RedisNotificationMessage) -> None:
        """Publish a typed notification message to Redis for SSE delivery."""
        await self._redis.publish(self._notif_channel(user_id), notification.model_dump_json())

    async def open_notification_subscription(self, user_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._notif_channel(user_id)
        await pubsub.subscribe(channel)
        return SSERedisSubscription(pubsub, channel)
