from __future__ import annotations

import logging
from typing import ClassVar, Type, TypeVar

import redis.asyncio as redis
from pydantic import BaseModel

from app.domain.events.typed import BaseEvent
from app.schemas_pydantic.sse import RedisNotificationMessage, RedisSSEMessage

T = TypeVar("T", bound=BaseModel)


class SSERedisSubscription:
    """Subscription wrapper for Redis pubsub with typed message parsing."""

    def __init__(self, pubsub: redis.client.PubSub, channel: str, logger: logging.Logger) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self.logger = logger

    async def get(self, model: Type[T]) -> T | None:
        """Get next typed message from the subscription."""
        msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if not msg or msg.get("type") != "message":
            return None
        try:
            return model.model_validate_json(msg["data"])
        except Exception as e:
            self.logger.warning(
                f"Failed to parse Redis message on channel {self._channel}: {e}",
                extra={"channel": self._channel, "model": model.__name__},
            )
            return None

    async def close(self) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class SSERedisBus:
    """Redis-backed pub/sub bus for SSE event fan-out across workers."""

    SSE_ROUTED_TOPICS: ClassVar[list[str]] = [
        "execution_requested",
        "execution_queued",
        "execution_started",
        "execution_running",
        "execution_completed",
        "execution_failed",
        "execution_timeout",
        "execution_cancelled",
        "result_stored",
        "pod_created",
        "pod_scheduled",
        "pod_running",
        "pod_succeeded",
        "pod_failed",
        "pod_terminated",
        "pod_deleted",
    ]

    def __init__(
        self,
        redis_client: redis.Redis,
        logger: logging.Logger,
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

    async def publish_event(self, execution_id: str, event: BaseEvent) -> None:
        topic = type(event).topic()
        message = RedisSSEMessage(
            event_type=topic,
            execution_id=execution_id,
            data=event.model_dump(mode="json"),
        )
        await self._redis.publish(self._exec_channel(execution_id), message.model_dump_json())

    async def route_domain_event(self, event: BaseEvent) -> None:
        """Route a domain event to its Redis execution channel by execution_id."""
        data = event.model_dump()
        execution_id = data.get("execution_id")
        topic = type(event).topic()
        if not execution_id:
            self.logger.debug("Event %s has no execution_id, skipping", topic)
            return
        try:
            await self.publish_event(execution_id, event)
        except Exception as e:
            self.logger.error(
                "Failed to publish %s to Redis for %s: %s",
                topic, execution_id, e,
                exc_info=True,

            )

    async def open_subscription(self, execution_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._exec_channel(execution_id)
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)
        return SSERedisSubscription(pubsub, channel, self.logger)

    async def publish_notification(self, user_id: str, notification: RedisNotificationMessage) -> None:
        """Publish a typed notification message to Redis for SSE delivery."""
        await self._redis.publish(self._notif_channel(user_id), notification.model_dump_json())

    async def open_notification_subscription(self, user_id: str) -> SSERedisSubscription:
        pubsub = self._redis.pubsub()
        channel = self._notif_channel(user_id)
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)
        return SSERedisSubscription(pubsub, channel, self.logger)
